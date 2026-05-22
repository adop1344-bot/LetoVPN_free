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
import warnings
import urllib3
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

# Отключаем предупреждения
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----- КОНФИГУРАЦИЯ -----
SOURCES_FILE = "sources.txt"
FLAGS_FILE = "flags.txt"
KEYWORDS_FILE = "keywords.txt"
CITIES_FILE = "cities.txt"
DOMAINS_FILE = "domains.txt"
TIMEOUT = 3.0
MAX_WORKERS = 500
PING_GOOD_THRESHOLD = 200
PING_MAX = 10000
GEOIP_URL = "https://cdn.jsdelivr.net/npm/geolite2-country/GeoLite2-Country.mmdb.gz"
GEOIP_FILE = "GeoLite2-Country.mmdb"

# ----- TELEGRAM УВЕДОМЛЕНИЯ -----
def send_telegram(message: str):
    """Отправляет сообщение в Telegram"""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
    except:
        pass

def log_and_send(message: str):
    """Выводит в консоль и отправляет в Telegram"""
    print(message)
    send_telegram(message)

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

# ----- ЗАГРУЗКА ФАЙЛОВ -----
def load_sources() -> List[str]:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except:
        return []

def load_flags() -> dict:
    code_to_flag = {}
    try:
        with open(FLAGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, flag = line.strip().split(':', 1)
                    code_to_flag[code] = flag
    except:
        pass
    return code_to_flag

def load_keywords() -> dict:
    keywords = {}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, words_str = line.strip().split(':', 1)
                    keywords[code] = [w.strip().lower() for w in words_str.split(',')]
    except:
        pass
    return keywords

def load_cities() -> dict:
    cities = {}
    try:
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    mask, city = line.strip().split(':', 1)
                    cities[mask] = city
    except:
        pass
    return cities

def load_domains() -> dict:
    domain_to_country = {}
    try:
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if ':' in line:
                        domain, code = line.split(':', 1)
                        domain_to_country[domain.lower()] = code
    except:
        pass
    return domain_to_country

SOURCES = load_sources()
COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()
DOMAIN_MAP = load_domains()

# ----- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -----
def get_protocol(config: str) -> str:
    if config.startswith('vless://'): return "VLESS"
    elif config.startswith('vmess://'): return "VMESS"
    elif config.startswith('trojan://'): return "TROJAN"
    return ""

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    if config.startswith('vless://'):
        match = re.search(r'vless://[^@]+@([^:?#]+):(\d+)', config)
        if match:
            return match.group(1), int(match.group(2))
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:] + '=' * (4 - len(config[8:]) % 4)
            data = json.loads(base64.b64decode(b64))
            return data.get('add'), int(data.get('port', 0))
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

def fetch_configs_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [line.strip() for line in r.text.splitlines() 
                if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

def process_config(config: str, reader) -> Optional[Tuple[str, str, float, str]]:
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    ping = tcp_ping(host, port, TIMEOUT)
    if ping is None or ping > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    protocol = get_protocol(config)
    
    flag, country_code = get_country_geoip(host, reader)
    if country_code == "ZZ":
        flag, country_code = detect_country_by_domain(host)
    if country_code == "ZZ":
        flag, country_code = detect_country_from_name(name_part)
    if country_code == "ZZ" or flag == "🏳️":
        return None
    
    lightning = "⚡" if ping < PING_GOOD_THRESHOLD else ""
    city = detect_city_by_ip(host) if country_code == "RU" else ""
    cidr = " обход белых листов" if '[*CIDR]' in name_part else ""
    domain_note = get_domain_note(host) if country_code == "RU" else ""

    if country_code == "RU":
        parts = [f"#{flag}"]
        if protocol: parts.append(protocol)
        if lightning: parts.append(lightning)
        if city: parts.append(f"({city})")
        if domain_note: parts.append(domain_note)
        new_name = ' '.join(parts) + cidr
    else:
        parts = [f"#{flag}"]
        if protocol: parts.append(protocol)
        if lightning: parts.append(lightning)
        new_name = ' '.join(parts) + cidr
    
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name
    
    # Для Telegram: флаг + протокол + статус
    status_emoji = "✅" if lightning else "⚠️"
    tg_message = f"{flag} {protocol} {status_emoji}"
    
    return (new_config, country_code, ping, tg_message)

def main():
    send_telegram("🚀 Запуск проверки конфигов...")
    
    if not SOURCES:
        send_telegram("❌ Нет источников! Проверьте sources.txt")
        return
    
    download_geoip_db()
    reader = init_geoip_reader()
    
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)
    
    all_configs = list(dict.fromkeys(all_configs))
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    
    send_telegram(f"📊 Загружено {len(filtered)} конфигов. Начинаю проверку...")
    
    results = []
    checked = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_config, cfg, reader) for cfg in filtered]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
                send_telegram(f"✅ {res[3]}")
            checked += 1
            if checked % 100 == 0:
                send_telegram(f"📊 Проверено {checked}/{len(filtered)} конфигов. Найдено {len(results)} рабочих.")
    
    # Финальное сообщение
    fast_count = len([r for r in results if '⚡' in r[3]])
    send_telegram(f"🎉 Готово! Найдено {len(results)} рабочих конфигов. ⚡{fast_count} быстрых, {len(results)-fast_count} обычных.")
    
    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping, _ in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping, _ in results if code != "RU"]
    other_configs.sort(key=lambda x: x[2])
    ru_configs.sort(key=lambda x: x[1])
    
    # Папка protocols
    os.makedirs("protocols", exist_ok=True)
    
    protocol_files = {"VLESS": [], "VMESS": [], "TROJAN": []}
    for cfg, code, ping, _ in results:
        if cfg.startswith('vless://'):
            protocol_files["VLESS"].append(cfg)
        elif cfg.startswith('vmess://'):
            protocol_files["VMESS"].append(cfg)
        elif cfg.startswith('trojan://'):
            protocol_files["TROJAN"].append(cfg)
    
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
    
    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")
            print(f"  protocols/{protocol}.txt: {len(configs)} конфигов")
    
    print(f"\nГотово! configs.txt ({len(other_configs)}), ru.txt ({len(ru_configs)})")
    for protocol, configs in protocol_files.items():
        if configs:
            print(f"  protocols/{protocol}.txt: {len(configs)} конфигов")
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()
