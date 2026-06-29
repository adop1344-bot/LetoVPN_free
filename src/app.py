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
from src.ping import verify_config, extract_host_port, get_protocol, init_xray, USE_TCP_FALLBACK
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

def process_config(config: str, reader) -> Optional[Tuple[str, str, float, tuple, float]]:
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    # Двухступенчатая проверка: TCP → Xray
    ping, is_working, used_xray = verify_config(config, host, port, TIMEOUT)
    if not is_working or ping is None or ping > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    protocol = get_protocol(config)
    
    # Метка, если использован TCP fallback
    tcp_label = ""
    if not used_xray and USE_TCP_FALLBACK:
        tcp_label = " [TCP]"
    
    # Определяем страну через GeoIP (приоритет)
    flag, country_code = get_country_geoip(host, reader)
    
    # Если GeoIP не определил, пробуем по домену
    if country_code == "ZZ":
        flag, country_code = detect_country_by_domain(host)
    
    # Особый случай: домен .ru
    is_ru_domain = host and host.lower().endswith('.ru')
    ru_domain_note = ""
    
    if is_ru_domain and country_code != "RU":
        flag = "🏳️"
        country_code = "??"
        ru_domain_note = " [?]"
    
    # Если страна всё ещё не определена (и не .ru домен) — используем название
    if country_code == "ZZ" and not is_ru_domain:
        flag, country_code = detect_country_from_name(name_part)
    
    # Если страна не определилась — пропускаем
    if country_code == "ZZ" or flag == "🏳️":
        return None
    
    lightning = "⚡" if ping < PING_GOOD_THRESHOLD else ""
    city = detect_city_by_ip(host) if country_code == "RU" else ""
    domain_note = get_domain_note(host) if country_code == "RU" else ""

    if country_code == "RU":
        parts = [f"#{flag}"]
        if protocol: parts.append(protocol)
        if lightning: parts.append(lightning)
        if tcp_label: parts.append(tcp_label)
        if city: parts.append(f"({city})")
        if domain_note: parts.append(domain_note)
        new_name = ' '.join(parts)
    else:
        parts = [f"#{flag}"]
        if protocol: parts.append(protocol)
        if lightning: parts.append(lightning)
        if tcp_label: parts.append(tcp_label)
        if ru_domain_note: parts.append(ru_domain_note)
        new_name = ' '.join(parts)
    
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name
    
    # Для Telegram
    tg_display = (flag, protocol, ping, lightning == "⚡")
    
    return (new_config, country_code, ping, tg_display, ping)

def main():
    start_time = time.time()
    
    # Инициализируем Xray
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
                new_config, country_code, ping, tg_display, raw_ping = res
                results.append(res)
            
            checked += 1
            
            if not start_sent:
                bot.send_start()
                start_sent = True
            
            if checked % 100 == 0:
                print(f"Обработано {checked}/{len(filtered)}. Найдено {len(results)}")
    
    fast_count = len([r for r in results if r[2] < PING_GOOD_THRESHOLD])
    bot.send_final(len(filtered), len(results), fast_count, time.time() - start_time)
    
    # --- СОРТИРОВКА ПО СТРАНАМ ---
    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping, _, _ in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping, _, _ in results if code != "RU" and code != "??"]
    
    # Сортируем по странам (по коду)
    other_configs.sort(key=lambda x: x[1])  # сортировка по коду страны
    ru_configs.sort(key=lambda x: x[1])      # сортировка по пингу (для ru.txt)
    
    # --- СОЗДАЁМ ФАЙЛЫ ---
    os.makedirs("protocols", exist_ok=True)
    
    protocol_files = {"VLESS": [], "VMESS": [], "TROJAN": []}
    for cfg, code, ping, _, _ in results:
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
    
    # --- ФАЙЛЫ С ЗАГОЛОВКАМИ ---
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    
    # --- ЧИСТЫЕ ФАЙЛЫ ДЛЯ HIDDIFY ---
    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов")
    
    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов")
    
    # --- ПРОТОКОЛЫ ---
    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")
    
    print(f"\nГотово!")
    print(f"  configs.txt: {len(other_configs)} конфигов (с заголовками, отсортировано по странам)")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов (чистый)")
    print(f"  ru.txt: {len(ru_configs)} конфигов (с заголовками)")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов (чистый)")
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()
