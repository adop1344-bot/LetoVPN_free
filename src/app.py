#!/usr/bin/env python3
import requests
import concurrent.futures
import os
import re
import gzip
import shutil
import time
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
        return "\U0001F9F3", "ZZ"
    host_lower = host.lower()
    for domain, code in sorted(DOMAIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if host_lower.endswith(domain):
            return COUNTRY_FLAGS.get(code, "\U0001F9F3"), code
    return "\U0001F9F3", "ZZ"

def detect_country_from_name(name: str) -> Tuple[str, str]:
    name_lower = name.lower()
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name:
            return flag, code
    for code, words in KEYWORDS.items():
        for word in words:
            if word in name_lower:
                return COUNTRY_FLAGS.get(code, "\U0001F9F3"), code
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match and match.group(1) in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[match.group(1)], match.group(1)
    return "\U0001F9F3", "ZZ"

def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                code = response.country.iso_code
                return COUNTRY_FLAGS.get(code, "\U0001F9F3"), code
    except:
        pass
    return "\U0001F9F3", "ZZ"

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
    if host_lower.endswith('.ru') or host_lower.endswith('.\u0440\u0444') or host_lower.endswith('.su'):
        parts = host_lower.split('.')
        if len(parts) >= 2:
            return f" [{parts[-2]}.{parts[-1]}]"
    return ""

# ----- ФИЛЬТР БЕЗОПАСНОСТИ -----
def is_secure_config(config: str) -> bool:
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
        print(f"\u041E\u0448\u0438\u0431\u043A\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043A\u0438 {url}: {e}")
        return []

# Приоритет стран для сортировки (первыми идут)
COUNTRY_SORT_ORDER = {
    "NL": 0, "DE": 1, "FI": 2,
    "US": 3, "GB": 4, "FR": 5, "SG": 6, "CA": 7, "JP": 8,
    "AU": 9, "CH": 10, "AT": 11, "BE": 12, "DK": 13,
    "SE": 14, "NO": 15, "PL": 16, "CZ": 17, "EE": 18,
    "LV": 19, "LT": 20, "IE": 21, "IT": 22, "ES": 23,
    "PT": 24, "GR": 25, "RO": 26, "BG": 27, "HU": 28,
    "TR": 29, "IL": 30, "AE": 31, "ZA": 32, "BR": 33,
    "IN": 34, "MY": 35, "VN": 36, "TH": 37, "PH": 38,
    "ID": 39, "HK": 40, "KR": 41, "TW": 42, "RU": 99
}

COUNTRY_NAMES = {
    "RU": "\u0420\u043E\u0441\u0441\u0438\u044F", "US": "\u0421\u0428\u0410", "DE": "\u0413\u0435\u0440\u043C\u0430\u043D\u0438\u044F", "FR": "\u0424\u0440\u0430\u043D\u0446\u0438\u044F",
    "NL": "\u041D\u0438\u0434\u0435\u0440\u043B\u0430\u043D\u0434\u044B", "GB": "\u0412\u0435\u043B\u0438\u043A\u043E\u0431\u0440\u0438\u0442\u0430\u043D\u0438\u044F", "JP": "\u042F\u043F\u043E\u043D\u0438\u044F",
    "SG": "\u0421\u0438\u043D\u0433\u0430\u043F\u0443\u0440", "CA": "\u041A\u0430\u043D\u0430\u0434\u0430", "AU": "\u0410\u0432\u0441\u0442\u0440\u0430\u043B\u0438\u044F",
    "BR": "\u0411\u0440\u0430\u0437\u0438\u043B\u0438\u044F", "IN": "\u0418\u043D\u0434\u0438\u044F", "IT": "\u0418\u0442\u0430\u043B\u0438\u044F", "ES": "\u0418\u0441\u043F\u0430\u043D\u0438\u044F",
    "CH": "\u0428\u0432\u0435\u0439\u0446\u0430\u0440\u0438\u044F", "AT": "\u0410\u0432\u0441\u0442\u0440\u0438\u044F", "BE": "\u0411\u0435\u043B\u044C\u0433\u0438\u044F",
    "DK": "\u0414\u0430\u043D\u0438\u044F", "FI": "\u0424\u0438\u043D\u043B\u044F\u043D\u0434\u0438\u044F", "NO": "\u041D\u043E\u0440\u0432\u0435\u0433\u0438\u044F",
    "SE": "\u0428\u0432\u0435\u0446\u0438\u044F", "PL": "\u041F\u043E\u043B\u044C\u0448\u0430", "CZ": "\u0427\u0435\u0445\u0438\u044F",
    "HU": "\u0412\u0435\u043D\u0433\u0440\u0438\u044F", "RO": "\u0420\u0443\u043C\u044B\u043D\u0438\u044F", "BG": "\u0411\u043E\u043B\u0433\u0430\u0440\u0438\u044F",
    "GR": "\u0413\u0440\u0435\u0446\u0438\u044F", "PT": "\u041F\u043E\u0440\u0442\u0443\u0433\u0430\u043B\u0438\u044F", "IE": "\u0418\u0440\u043B\u0430\u043D\u0434\u0438\u044F",
    "TR": "\u0422\u0443\u0440\u0446\u0438\u044F", "IL": "\u0418\u0437\u0440\u0430\u0438\u043B\u044C", "AE": "\u041E\u0410\u042D",
    "SA": "\u0421\u0430\u0443\u0434\u043E\u0432\u0441\u043A\u0430\u044F \u0410\u0440\u0430\u0432\u0438\u044F", "ZA": "\u042E\u0410\u0420", "MX": "\u041C\u0435\u043A\u0441\u0438\u043A\u0430",
    "AR": "\u0410\u0440\u0433\u0435\u043D\u0442\u0438\u043D\u0430", "CL": "\u0427\u0438\u043B\u0438", "CO": "\u041A\u043E\u043B\u0443\u043C\u0431\u0438\u044F",
    "MY": "\u041C\u0430\u043B\u0430\u0439\u0437\u0438\u044F", "VN": "\u0412\u044C\u0435\u0442\u043D\u0430\u043C", "TH": "\u0422\u0430\u0438\u043B\u0430\u043D\u0434",
    "PH": "\u0424\u0438\u043B\u0438\u043F\u043F\u0438\u043D\u044B", "ID": "\u0418\u043D\u0434\u043E\u043D\u0435\u0437\u0438\u044F", "PK": "\u041F\u0430\u043A\u0438\u0441\u0442\u0430\u043D",
    "EG": "\u0415\u0433\u0438\u043F\u0435\u0442", "NG": "\u041D\u0438\u0433\u0435\u0440\u0438\u044F", "MA": "\u041C\u0430\u0440\u043E\u043A\u043A\u043E",
    "KE": "\u041A\u0435\u043D\u0438\u044F", "NZ": "\u041D\u043E\u0432\u0430\u044F \u0417\u0435\u043B\u0430\u043D\u0434\u0438\u044F",
    "HK": "\u0413\u043E\u043D\u043A\u043E\u043D\u0433", "KR": "\u042E\u0436\u043D\u0430\u044F \u041A\u043E\u0440\u0435\u044F",
    "TW": "\u0422\u0430\u0439\u0432\u0430\u043D\u044C", "EE": "\u042D\u0441\u0442\u043E\u043D\u0438\u044F",
    "LV": "\u041B\u0430\u0442\u0432\u0438\u044F", "LT": "\u041B\u0438\u0442\u0432\u0430"
}

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
        flag = "\U0001F9F3"
        country_code = "??"
    
    if country_code == "ZZ" and not is_ru_domain:
        flag, country_code = detect_country_from_name(name_part)
    
    if country_code == "ZZ" or flag == "\U0001F9F3":
        return None
    
    country_name_ru = COUNTRY_NAMES.get(country_code, country_code)
    
    # Формируем новое название:
    # - Если sni содержит cloudflare -> "cloudflare" в начало
    # - sni не пишем в названии
    # - В конце t.me/letovpn_free
    parts = []
    
    # Cloudflare в начало если есть
    if sni and "cloudflare" in sni.lower():
        parts.append("cloudflare")
    
    parts.append(flag)
    parts.append(country_name_ru)
    
    # В конце t.me/letovpn_free
    parts.append("t.me/letovpn_free")
    
    new_name = ' '.join(parts)
    
    if '#' in config:
        new_config = config.split('#', 1)[0] + '#' + new_name
    else:
        new_config = config + '#' + new_name
    
    tg_display = (flag, protocol, ping, ping < PING_GOOD_THRESHOLD)
    
    return (new_config, country_code, ping, tg_display, ping, speed_mbps)


def save_chunked_files(all_configs_with_country, base_name, chunk_size=200):
    """Сохраняет конфиги в файлы по chunk_size штук"""
    total = len(all_configs_with_country)
    if total == 0:
        return
    
    # Удаляем старые файлы
    i = 1
    while os.path.exists(f"{base_name}{i}.txt"):
        os.remove(f"{base_name}{i}.txt")
        i += 1
    
    for i in range(0, total, chunk_size):
        chunk = all_configs_with_country[i:i+chunk_size]
        file_num = i // chunk_size + 1
        with open(f"{base_name}{file_num}.txt", "w", encoding="utf-8") as f:
            for cfg, _ in chunk:
                f.write(cfg + "\n")
        print(f"  {base_name}{file_num}.txt: {len(chunk)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")


def main():
    start_time = time.time()
    
    init_xray()
    
    if not SOURCES:
        print("\u041D\u0435\u0442 \u0438\u0441\u0442\u043E\u0447\u043D\u0438\u043A\u043E\u0432! \u041F\u0440\u043E\u0432\u0435\u0440\u044C\u0442\u0435 sources.txt")
        return
    
    bot = TelegramBot()
    
    download_geoip_db()
    reader = init_geoip_reader()
    
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
        all_configs.extend(cfgs)
    
    all_configs = list(dict.fromkeys(all_configs))
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    
    print(f"\u0412\u0441\u0435\u0433\u043E \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432: {len(filtered)}")
    
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
                print(f"\u041E\u0431\u0440\u0430\u0431\u043E\u0442\u0430\u043D\u043E {checked}/{len(filtered)}. \u041D\u0430\u0439\u0434\u0435\u043D\u043E {len(results)}")
    
    fast_count = len([r for r in results if r[2] < PING_GOOD_THRESHOLD])
    bot.send_final(len(filtered), len(results), fast_count, time.time() - start_time)
    
    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping, _, _, _ in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping, _, _, _ in results if code != "RU" and code != "??"]
    
    # Сортировка: по приоритету стран, потом по пингу
    def sort_key(item):
        cfg, code, ping = item
        order = COUNTRY_SORT_ORDER.get(code, 50)
        return (order, ping)
    
    other_configs.sort(key=sort_key)
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
    common_header = f"""#announce: \u041E\u0431\u043D\u043E\u0432\u043B\u0435\u043D\u043E: {now}, \u0431\u043E\u043B\u044C\u0448\u0435 \u0432 \u0442\u0435\u043B\u0435\u0433\u0440\u0430\u043C \u043A\u0430\u043D\u0430\u043B\u0435 @LetoVPN_free!
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    
    # 1. configs.txt - все конфиги (кроме RU)
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    print(f"  configs.txt: {len(other_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    
    # 2. configs1.txt, configs2.txt... по 200 конфигов
    other_simple = [(cfg, ping) for cfg, _, ping in other_configs]
    save_chunked_files(other_simple, "configs", 200)
    
    # 3. ru.txt
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    print(f"  ru.txt: {len(ru_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    
    # Чистые файлы для Hiddify
    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    print(f"  configs_hiddify.txt: {len(other_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    
    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    print(f"  ru_hiddify.txt: {len(ru_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    
    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")
    
    print(f"\n\u0413\u043E\u0442\u043E\u0432\u043E!")
    print(f"  configs.txt: {len(other_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    print(f"  configs_hiddify.txt: {len(other_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432 (\u0447\u0438\u0441\u0442\u044B\u0439)")
    print(f"  ru.txt: {len(ru_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432")
    print(f"  ru_hiddify.txt: {len(ru_configs)} \u043A\u043E\u043D\u0444\u0438\u0433\u043E\u0432 (\u0447\u0438\u0441\u0442\u044B\u0439)")
    
    if reader:
        reader.close()

if __name__ == "__main__":
    main()