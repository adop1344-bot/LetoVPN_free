#!/usr/bin/env python3
import requests
import concurrent.futures
import socket
import time
import base64
import json
import os
import re
import gzip
import shutil
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

# ----- КОНФИГУРАЦИЯ -----
SOURCES_FILE = "sources.txt"
FLAGS_FILE = "flags.txt"
KEYWORDS_FILE = "keywords.txt"
CITIES_FILE = "cities.txt"
TIMEOUT = 3.0
MAX_WORKERS = 500
PING_GOOD_THRESHOLD = 200
PING_MAX = 10000
RETRY_PING = True
GEOIP_URL = "https://cdn.jsdelivr.net/npm/geolite2-country/GeoLite2-Country.mmdb.gz"
GEOIP_FILE = "GeoLite2-Country.mmdb"

# ----- ЗАГРУЗКА GEOIP БАЗЫ -----
def download_geoip_db():
    if os.path.exists(GEOIP_FILE):
        print(f"База GeoIP уже есть: {GEOIP_FILE}")
        return True
    print("Скачиваю GeoLite2 базу...")
    try:
        r = requests.get(GEOIP_URL, timeout=30)
        r.raise_for_status()
        with open(GEOIP_FILE + ".gz", "wb") as f:
            f.write(r.content)
        with gzip.open(GEOIP_FILE + ".gz", "rb") as f_in:
            with open(GEOIP_FILE, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(GEOIP_FILE + ".gz")
        print("База GeoIP загружена")
        return True
    except Exception as e:
        print(f"Ошибка загрузки GeoIP: {e}")
        return False

def init_geoip_reader():
    try:
        import geoip2.database
        if os.path.exists(GEOIP_FILE):
            return geoip2.database.Reader(GEOIP_FILE)
    except ImportError:
        print("geoip2 не установлен, использую только парсинг названий")
    return None

# ----- ЗАГРУЗКА ВНЕШНИХ ФАЙЛОВ -----
def load_sources() -> List[str]:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print(f"Ошибка: {SOURCES_FILE} не найден")
        return []

def load_flags() -> dict:
    code_to_flag = {}
    try:
        with open(FLAGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, flag = line.strip().split(':', 1)
                    code_to_flag[code] = flag
    except FileNotFoundError:
        print(f"Ошибка: {FLAGS_FILE} не найден")
    return code_to_flag

def load_keywords() -> dict:
    keywords = {}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, words_str = line.strip().split(':', 1)
                    keywords[code] = [w.strip().lower() for w in words_str.split(',')]
    except FileNotFoundError:
        print(f"Ошибка: {KEYWORDS_FILE} не найден")
    return keywords

def load_cities() -> dict:
    cities = {}
    try:
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    mask, city = line.strip().split(':', 1)
                    cities[mask] = city
    except FileNotFoundError:
        print(f"Ошибка: {CITIES_FILE} не найден")
    return cities

# ----- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ -----
SOURCES = load_sources()
COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()

# ----- ОПРЕДЕЛЕНИЕ СТРАНЫ ПО НАЗВАНИЮ (FALLBACK) -----
def detect_country_from_name(name: str) -> Tuple[str, str]:
    """Парсит название конфига, возвращает (флаг, код_страны)"""
    name_lower = name.lower()
    
    # 1. Ищем флаг в тексте
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name:
            return flag, code
    
    # 2. Ищем ключевые слова
    for code, words in KEYWORDS.items():
        for word in words:
            if word in name_lower:
                flag = COUNTRY_FLAGS.get(code, "🏳️")
                return flag, code
    
    # 3. Ищем двухбуквенный код
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match:
        code = match.group(1)
        flag = COUNTRY_FLAGS.get(code, "🏳️")
        return flag, code
    
    return "🏳️", "ZZ"

def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    """Определяет страну через GeoIP базу"""
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                code = response.country.iso_code
                flag = COUNTRY_FLAGS.get(code, "🏳️")
                return flag, code
    except Exception:
        pass
    return "🏳️", "ZZ"

def detect_city_by_ip(host: str) -> str:
    """Определяет город по маске IP из cities.txt"""
    if not re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return ""
    parts = host.split('.')
    if len(parts) < 2:
        return ""
    mask = f"{parts[0]}.{parts[1]}"
    return CITIES.get(mask, "")

# ----- ОСНОВНЫЕ ФУНКЦИИ -----
def fetch_configs_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [line.strip() for line in r.text.splitlines() 
                if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    if config.startswith('vless://'):
        match = re.search(r'vless://[^@]+@([^:?#]+):(\d+)', config)
        if match:
            return match.group(1), int(match.group(2))
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:] + '=' * (4 - len(config[8:]) % 4)
            data = json.loads(base64.b64decode(b64))
            host = data.get('add')
            port = data.get('port')
            if host and port:
                return host, int(port)
        except:
            pass
    elif config.startswith('trojan://'):
        match = re.search(r'trojan://[^@]+@([^:?#]+):(\d+)', config)
        if match:
            return match.group(1), int(match.group(2))
    return None, None

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def check_config(host: str, port: int) -> Optional[float]:
    p1 = tcp_ping(host, port, TIMEOUT)
    if p1 is None:
        return None
    if RETRY_PING:
        time.sleep(0.5)
        p2 = tcp_ping(host, port, TIMEOUT)
        return min(p1, p2) if p2 is not None else p1
    return p1

def process_config(config: str, reader) -> Optional[Tuple[str, str, float]]:
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    ping = check_config(host, port)
    if ping is None or ping > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    
    # Гибридное определение страны: GeoIP + fallback по названию
    flag, country_code = get_country_geoip(host, reader)
    if country_code == "ZZ":
        flag, country_code = detect_country_from_name(name_part)
    
    lightning = "⚡" if ping < PING_GOOD_THRESHOLD else ""
    city = detect_city_by_ip(host) if country_code == "RU" else ""
    cidr = " обход белых листов" if '[*CIDR]' in name_part else ""

    # Формируем название
    if country_code == "RU":
        parts = [f"#{flag}"]
        if lightning:
            parts.append(lightning)
        if city:
            parts.append(f"({city})")
        new_name = ''.join(parts) + cidr
    else:
        new_name = f"#{flag}{lightning}{cidr}"
    
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name
    
    return (new_config, country_code, ping)

def main():
    if not SOURCES:
        print("Нет источников! Проверьте sources.txt")
        return
    
    # Загружаем GeoIP
    download_geoip_db()
    reader = init_geoip_reader()
    
    print("Загрузка конфигов...")
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)
    
    print(f"Всего: {len(all_configs)}")
    all_configs = list(dict.fromkeys(all_configs))
    print(f"Уникальных: {len(all_configs)}")
    
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    print(f"После anycast: {len(filtered)}")
    
    # Многопоточная обработка
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_config, cfg, reader) for cfg in filtered]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            res = future.result()
            if res:
                results.append(res)
            if i % 100 == 0:
                print(f"Обработано {i}/{len(filtered)}")
    
    print(f"Работоспособных: {len(results)}")
    
    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping in results if code != "RU"]
    other_configs.sort(key=lambda x: x[1])
    ru_configs.sort(key=lambda x: x[1])
    
    # Заголовки
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_USERNAME/YOUR_REPO")
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
    
    print(f"Готово! configs.txt ({len(other_configs)}), ru.txt ({len(ru_configs)})")
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()
