#!/usr/bin/env python3
"""
Локальный тест конфигов с проверкой через HTTP прокси
Запуск: python test_local.py
"""

import sys
import os
import subprocess
import warnings
import urllib3

# Отключаем предупреждения о SSL
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import load_sources, load_flags, load_keywords, load_cities, load_domains
from src.ping import tcp_ping, extract_host_port, get_protocol
import requests
import time
import concurrent.futures
import re
from datetime import datetime, timezone, timedelta

# Загружаем настройки
SOURCES = load_sources()
COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()
DOMAIN_MAP = load_domains()

# ----- ФУНКЦИИ ГЕО -----
def detect_country_by_domain(host: str):
    if not host:
        return "🏳️", "ZZ"
    host_lower = host.lower()
    for domain, code in sorted(DOMAIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if host_lower.endswith(domain):
            return COUNTRY_FLAGS.get(code, "🏳️"), code
    return "🏳️", "ZZ"

def detect_country_from_name(name: str):
    name_lower = name.lower()
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name:
            return flag, code
    for code, words in KEYWORDS.items():
        for word in words:
            if word in name_lower:
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match and match.group(1) in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[match.group(1)], match.group(1)
    return "🏳️", "ZZ"

def get_country_geoip(host: str, reader):
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                code = response.country.iso_code
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    except:
        pass
    return "🏳️", "ZZ"

def get_geoip_reader():
    try:
        import geoip2.database
        if os.path.exists("GeoLite2-Country.mmdb"):
            return geoip2.database.Reader("GeoLite2-Country.mmdb")
    except:
        pass
    return None

def fetch_configs_from_url(url: str):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [line.strip() for line in r.text.splitlines() 
                if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

def is_secure_config(config: str) -> bool:
    """Проверяет безопасность конфига"""
    config_lower = config.lower()
    if 'allowinsecure=1' in config_lower or 'insecure=1' in config_lower:
        return False
    if 'security=none' in config_lower or 'tls=none' in config_lower:
        return False
    return True

# ----- ПРОВЕРКА ЧЕРЕЗ HTTP ПРОКСИ -----
def check_via_proxy(host: str, port: int, timeout: float = 2.0) -> tuple:
    """
    Проверяет конфиг через HTTP GET запрос через прокси
    Возвращает: (ping_ms, is_working)
    """
    proxy_types = [
        f"socks5://{host}:{port}",
        f"socks5h://{host}:{port}",
        f"http://{host}:{port}",
        f"https://{host}:{port}"
    ]
    
    # Только одна ссылка для проверки
    test_url = "http://cp.cloudflare.com/generate_204"
    
    for proxy_type in proxy_types:
        proxies = {"http": proxy_type, "https": proxy_type}
        
        try:
            start = time.time()
            response = requests.get(
                test_url,
                proxies=proxies,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0"},
                verify=False
            )
            elapsed = (time.time() - start) * 1000
            
            # 204 - успех, 200, 301, 302 - тоже ок
            if response.status_code in [200, 204, 301, 302]:
                return (elapsed, True)
        except:
            continue
    
    return (None, False)

def check_config_dual(host: str, port: int, timeout: float = 2.0) -> tuple:
    """
    Двойная проверка: TCP + HTTP через прокси
    Возвращает: (ping_ms, is_working)
    """
    # 1. TCP ping (быстро)
    tcp_ping_result = tcp_ping(host, port, timeout)
    if tcp_ping_result is None:
        return (None, False)
    
    # 2. HTTP через прокси (точно)
    http_ping, http_ok = check_via_proxy(host, port, timeout)
    
    if http_ok and http_ping is not None:
        return (http_ping, True)
    
    # Если HTTP не прошёл — конфиг мёртв (даже если TCP прошёл)
    return (None, False)

def process_config_local(config: str, reader):
    if not is_secure_config(config):
        return None
    
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    # Двойная проверка: TCP + HTTP через прокси
    ping, is_working = check_config_dual(host, port, 2.0)
    if not is_working or ping is None or ping > 10000:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    protocol = get_protocol(config)
    
    # Извлекаем SNI
    sni_match = re.search(r'sni=([^&]+)', config)
    sni = sni_match.group(1) if sni_match else ""

    flag, country_code = get_country_geoip(host, reader)
    if country_code == "ZZ":
        flag, country_code = detect_country_by_domain(host)
    if country_code == "ZZ":
        flag, country_code = detect_country_from_name(name_part)
    if country_code == "ZZ" or flag == "🏳️":
        return None

    lightning = "⚡" if ping < 200 else ""
    
    country_names = {
        "RU": "Россия", "US": "США", "DE": "Германия", "FR": "Франция",
        "NL": "Нидерланды", "GB": "Великобритания", "JP": "Япония",
        "SG": "Сингапур", "CA": "Канада", "AU": "Австралия",
        "BR": "Бразилия", "IN": "Индия", "IT": "Италия", "ES": "Испания",
        "CH": "Швейцария", "AT": "Австрия", "BE": "Бельгия",
        "DK": "Дания", "FI": "Финляндия", "NO": "Норвегия",
        "SE": "Швеция", "PL": "Польша", "CZ": "Чехия",
        "HU": "Венгрия", "RO": "Румыния", "BG": "Болгария",
        "GR": "Греция", "PT": "Португалия", "IE": "Ирландия",
        "TR": "Турция", "IL": "Израиль", "AE": "ОАЭ",
        "SA": "Саудовская Аравия", "ZA": "ЮАР", "MX": "Мексика",
        "AR": "Аргентина", "CL": "Чили", "CO": "Колумбия",
        "MY": "Малайзия", "VN": "Вьетнам", "TH": "Таиланд",
        "PH": "Филиппины", "ID": "Индонезия", "PK": "Пакистан",
        "EG": "Египет", "NG": "Нигерия", "MA": "Марокко",
        "KE": "Кения", "NZ": "Новая Зеландия"
    }
    country_name_ru = country_names.get(country_code, country_code)
    
    # Формируем название: 🇺🇸 США sni=ya.ru
    parts = [flag, country_name_ru]
    if lightning:
        parts.append(lightning)
    if sni:
        parts.append(f"sni={sni}")
    else:
        parts.append("sni=no-sni")
    
    new_name = ' '.join(parts)
    
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name
    
    return {
        "config": new_config,
        "host": host,
        "port": port,
        "ping": round(ping),
        "protocol": protocol,
        "flag": flag,
        "country": country_code,
        "lightning": lightning,
        "sni": sni
    }

def create_checked_files(configs):
    """Разбивает конфиги на файлы по 200 штук"""
    chunk_size = 200
    total = len(configs)
    if total == 0:
        return
    
    for i in range(1, 11):
        if os.path.exists(f"checked{i}.txt"):
            os.remove(f"checked{i}.txt")
    
    for i in range(0, total, chunk_size):
        chunk = configs[i:i+chunk_size]
        file_num = i // chunk_size + 1
        if file_num <= 10:
            with open(f"checked{file_num}.txt", "w", encoding="utf-8") as f:
                for cfg in chunk:
                    f.write(cfg + "\n")
            print(f"  checked{file_num}.txt: {len(chunk)} конфигов")

def save_results(results, ru_configs, other_configs, protocol_files):
    """Сохраняет результаты в файлы"""
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = "adop1344-bot/LetoVPN_free"
    common_header = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    
    os.makedirs("protocols", exist_ok=True)
    
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    
    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    
    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    
    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")
    
    all_configs = [cfg for cfg, _, _ in other_configs] + [cfg for cfg, _ in ru_configs]
    create_checked_files(all_configs)

def git_push():
    """Пушит изменения в GitHub"""
    try:
        print("\n📤 Отправка в GitHub...")
        subprocess.run(["git", "config", "user.name", "Termux"], check=True)
        subprocess.run(["git", "config", "user.email", "termux@local"], check=True)
        subprocess.run(["git", "add", "configs.txt", "ru.txt", "configs_hiddify.txt", "ru_hiddify.txt", "checked*.txt", "protocols/"], check=True, shell=True)
        subprocess.run(["git", "commit", "-m", f"Auto-update from Termux {datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("✅ Отправлено в GitHub!")
        return True
    except Exception as e:
        print(f"❌ Ошибка пуша: {e}")
        print("Попробуй выполнить вручную:")
        print("  git add .")
        print("  git commit -m 'update'")
        print("  git push")
        return False

def main():
    print("🚀 LetoVPN — локальный тест (TCP + HTTP прокси)")
    print("=" * 50)
    
    if not os.path.exists(".git"):
        print("❌ Ошибка: запусти скрипт из папки репозитория")
        print("   cd LetoVPN_free")
        return
    
    reader = get_geoip_reader()
    if reader:
        print("✅ GeoIP загружена")
    
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)
    
    all_configs = list(dict.fromkeys(all_configs))
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    print(f"Всего конфигов: {len(filtered)}")
    print("=" * 50)
    
    results = []
    start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(process_config_local, cfg, reader) for cfg in filtered]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            res = future.result()
            if res:
                results.append(res)
            if i % 50 == 0:
                print(f"Проверено {i}/{len(filtered)}. Найдено {len(results)}")
    
    elapsed = time.time() - start
    
    results.sort(key=lambda x: x["ping"])
    
    ru_configs = [(r["config"], r["ping"]) for r in results if r["country"] == "RU"]
    other_configs = [(r["config"], r["country"], r["ping"]) for r in results if r["country"] != "RU" and r["country"] != "??"]
    
    protocol_files = {"VLESS": [], "VMESS": [], "TROJAN": []}
    for r in results:
        if r["country"] == "??":
            continue
        if r["config"].startswith('vless://'): protocol_files["VLESS"].append(r["config"])
        elif r["config"].startswith('vmess://'): protocol_files["VMESS"].append(r["config"])
        elif r["config"].startswith('trojan://'): protocol_files["TROJAN"].append(r["config"])
    
    save_results(results, ru_configs, other_configs, protocol_files)
    
    print("=" * 50)
    print(f"✅ Проверено: {len(filtered)}")
    print(f"🎯 Рабочих: {len(results)}")
    print(f"⏱ Время: {elapsed:.1f} сек")
    print(f"📁 configs.txt: {len(other_configs)} конфигов")
    print(f"📁 ru.txt: {len(ru_configs)} конфигов")
    print("=" * 50)
    
    print("\n🏆 ТОП-10 (самые быстрые):")
    for i, r in enumerate(results[:10], 1):
        flag = r["flag"]
        proto = r["protocol"]
        ping = r["ping"]
        lightning = r["lightning"]
        host = r["host"]
        print(f"{i:2}. {flag}{proto} {ping}ms {lightning}  {host}")
    
    if results:
        git_push()
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()
