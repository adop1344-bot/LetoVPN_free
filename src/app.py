#!/usr/bin/env python3
import requests
import concurrent.futures
import os
import re
import gzip
import shutil
import time
import json
import warnings
import urllib3
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

# Импорт модулей из src
from src.config import (
    TIMEOUT, MAX_WORKERS, PING_GOOD_THRESHOLD, PING_MAX,
    GEOIP_URL, GEOIP_FILE,
    load_sources, load_flags, load_keywords, load_cities, load_domains
)
from src.ping import verify_config, extract_host_port, get_protocol, init_xray
from src.tg import TelegramBot

# Отключаем предупреждения
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Загружаем данные
SOURCES = load_sources()
COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()
DOMAIN_MAP = load_domains()

# ----- ФУНКЦИИ ГЕО -----
def detect_country_by_domain(host: str) -> Tuple[str, str]:
    if not host:
        return "🏳️", "ZZ"
    host_lower = host.lower()
    for domain, code in sorted(DOMAIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if host_lower.endswith(domain):
            return COUNTRY_FLAGS.get(code, "🏳️"), code
    return "🏳️", "ZZ"

def detect_country_from_name(name: str) -> Tuple[str, str]:
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

def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                code = response.country.iso_code
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    except:
        pass
    return "🏳️", "ZZ"

def detect_city_by_ip(host: str) -> str:
    if not re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return ""
    parts = host.split('.')
    mask = f"{parts[0]}.{parts[1]}"
    return CITIES.get(mask, "")

def get_domain_note(host: str) -> str:
    if not host:
        return ""
    host_lower = host.lower()
    if host_lower.endswith('.ru') or host_lower.endswith('.рф') or host_lower.endswith('.su'):
        parts = host_lower.split('.')
        if len(parts) >= 2:
            return f" [{parts[-2]}.{parts[-1]}]"
    return ""

# ----- ФИЛЬТР БЕЗОПАСНОСТИ -----
def is_secure_config(config: str) -> bool:
    """Проверяет, есть ли в конфиге insecure или none параметры"""
    config_lower = config.lower()
    if 'allowinsecure=1' in config_lower or 'insecure=1' in config_lower:
        return False
    if 'security=none' in config_lower or 'tls=none' in config_lower:
        return False
    return True

# ----- ЗАГРУЗКА GEOIP -----
def download_geoip_db():
    if os.path.exists(GEOIP_FILE):
        return True
    try:
        r = requests.get(GEOIP_URL, timeout=30)
        r.raise_for_status()
        with open(GEOIP_FILE + ".gz", "wb") as f:
            f.write(r.content)
        with gzip.open(GEOIP_FILE + ".gz", "rb") as f_in:
            with open(GEOIP_FILE, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(GEOIP_FILE + ".gz")
        return True
    except:
        return False

def init_geoip_reader():
    try:
        import geoip2.database
        if os.path.exists(GEOIP_FILE):
            return geoip2.database.Reader(GEOIP_FILE)
    except:
        pass
    return None

def fetch_configs_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [line.strip() for line in r.text.splitlines() 
                if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

def process_config(config: str, reader) -> Optional[Tuple[str, str, float, tuple, float, float]]:
    # Фильтр безопасности
    if not is_secure_config(config):
        return None
    
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    ping, is_working, used_xray, speed_mbps = verify_config(config, host, port, TIMEOUT)
    if not is_working or ping is None or ping > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    protocol = get_protocol(config)
    
    # Извлекаем SNI
    sni_match = re.search(r'sni=([^&]+)', config)
    sni = sni_match.group(1) if sni_match else ""
    
    # Определяем страну через GeoIP (приоритет)
    flag, country_code = get_country_geoip(host, reader)
    
    if country_code == "ZZ":
        flag, country_code = detect_country_by_domain(host)
    
    is_ru_domain = host and host.lower().endswith('.ru')
    
    if is_ru_domain and country_code != "RU":
        flag = "🏳️"
        country_code = "??"
    
    if country_code == "ZZ" and not is_ru_domain:
        flag, country_code = detect_country_from_name(name_part)
    
    if country_code == "ZZ" or flag == "🏳️":
        return None
    
    # Скорость
    speed_str = ""
    if speed_mbps is not None and speed_mbps > 1:
        speed_str = f"{speed_mbps:.0f}Mbps"
    
    # Название страны
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
    
    # Формируем новое название: 🇺🇸 США 45Mbps sni=ya.ru
    parts = []
    parts.append(f"{flag}")
    parts.append(country_name_ru)
    if speed_str:
        parts.append(speed_str)
    if sni:
        parts.append(f"sni={sni}")
    else:
        parts.append("sni=no-sni")
    
    new_name = ' '.join(parts)
    
    # Исправлено: добавляем # перед new_name
    if '#' in config:
        new_config = config.split('#', 1)[0] + '#' + new_name
    else:
        new_config = config + '#' + new_name
    
    tg_display = (flag, protocol, ping, ping < PING_GOOD_THRESHOLD)
    
    return (new_config, country_code, ping, tg_display, ping, speed_mbps)

def main():
    start_time = time.time()
    
    init_xray()
    
    if not SOURCES:
        print("Нет источников! Проверьте sources.txt")
        return
    
    bot = TelegramBot()
    
    download_geoip_db()
    reader = init_geoip_reader()
    
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)
    
    all_configs = list(dict.fromkeys(all_configs))
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    
    print(f"Всего конфигов: {len(filtered)}")
    
    results = []
    checked = 0
    start_sent = False
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_config, cfg, reader) for cfg in filtered]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
            
            checked += 1
            
            if not start_sent:
                bot.send_start()
                start_sent = True
            
            if checked % 100 == 0:
                print(f"Обработано {checked}/{len(filtered)}. Найдено {len(results)}")
    
    fast_count = len([r for r in results if r[2] < PING_GOOD_THRESHOLD])
    bot.send_final(len(filtered), len(results), fast_count, time.time() - start_time)
    
    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping, _, _, _ in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping, _, _, _ in results if code != "RU" and code != "??"]
    
    other_configs.sort(key=lambda x: x[1])
    ru_configs.sort(key=lambda x: x[1])
    
    os.makedirs("protocols", exist_ok=True)
    
    protocol_files = {"VLESS": [], "VMESS": [], "TROJAN": []}
    for cfg, code, ping, _, _, _ in results:
        if code == "??":
            continue
        if cfg.startswith('vless://'): protocol_files["VLESS"].append(cfg)
        elif cfg.startswith('vmess://'): protocol_files["VMESS"].append(cfg)
        elif cfg.startswith('trojan://'): protocol_files["TROJAN"].append(cfg)
    
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "adop1344-bot/LetoVPN_free")
    common_header = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    
    # Чистые файлы для Hiddify
    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов")
    
    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов")
    
    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")
    
    print(f"\nГотово!")
    print(f"  configs.txt: {len(other_configs)} конфигов")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов (чистый)")
    print(f"  ru.txt: {len(ru_configs)} конфигов")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов (чистый)")
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()