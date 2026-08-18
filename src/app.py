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

from src.config import (
    TIMEOUT, MAX_WORKERS, PING_GOOD_THRESHOLD, PING_MAX,
    GEOIP_URL, GEOIP_FILE,
    load_sources, load_flags, load_keywords, load_cities, load_domains
)
from src.ping import verify_config, extract_host_port, get_protocol, init_xray
from src.tg import TelegramBot

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCES = load_sources()
COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()
DOMAIN_MAP = load_domains()

WHITE_FLAG = "\U0001F9F3"

def detect_country_by_domain(host: str) -> Tuple[str, str]:
    if not host: return WHITE_FLAG, "ZZ"
    host_lower = host.lower()
    for domain, code in sorted(DOMAIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if host_lower.endswith(domain):
            return COUNTRY_FLAGS.get(code, WHITE_FLAG), code
    return WHITE_FLAG, "ZZ"

def detect_country_from_name(name: str) -> Tuple[str, str]:
    name_lower = name.lower()
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name: return flag, code
    for code, words in KEYWORDS.items():
        for word in words:
            if word in name_lower: return COUNTRY_FLAGS.get(code, WHITE_FLAG), code
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match and match.group(1) in COUNTRY_FLAGS: return COUNTRY_FLAGS[match.group(1)], match.group(1)
    return WHITE_FLAG, "ZZ"

def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                return COUNTRY_FLAGS.get(response.country.iso_code, WHITE_FLAG), response.country.iso_code
    except: pass
    return WHITE_FLAG, "ZZ"

def detect_city_by_ip(host: str) -> str:
    if not re.match(r'^\d+\.\d+\.\d+\.\d+$', host): return ""
    return CITIES.get(f"{host.split('.')[0]}.{host.split('.')[1]}", "")

def get_domain_note(host: str) -> str:
    if not host: return ""
    hl = host.lower()
    if hl.endswith('.ru') or hl.endswith('.xn--p1ai') or hl.endswith('.su'):
        p = hl.split('.')
        if len(p) >= 2: return f" [{p[-2]}.{p[-1]}]"
    return ""

def is_secure_config(config: str) -> bool:
    cl = config.lower()
    if 'allowinsecure=1' in cl or 'insecure=1' in cl: return False
    if 'security=none' in cl or 'tls=none' in cl: return False
    return True

def download_geoip_db():
    if os.path.exists(GEOIP_FILE): return True
    try:
        r = requests.get(GEOIP_URL, timeout=30)
        r.raise_for_status()
        with open(GEOIP_FILE + ".gz", "wb") as f: f.write(r.content)
        with gzip.open(GEOIP_FILE + ".gz", "rb") as fi:
            with open(GEOIP_FILE, "wb") as fo: shutil.copyfileobj(fi, fo)
        os.remove(GEOIP_FILE + ".gz")
        return True
    except: return False

def init_geoip_reader():
    try:
        import geoip2.database
        if os.path.exists(GEOIP_FILE): return geoip2.database.Reader(GEOIP_FILE)
    except: pass
    return None

def fetch_configs_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [l.strip() for l in r.text.splitlines() if l.strip() and not l.startswith('#')]
    except Exception as e:
        print(f"Error loading {url}: {e}")
        return []

COUNTRY_SORT_ORDER = {
    "NL": 0, "DE": 1, "FI": 2, "US": 3, "GB": 4, "FR": 5, "SG": 6, "CA": 7, "JP": 8,
    "AU": 9, "CH": 10, "AT": 11, "BE": 12, "DK": 13, "SE": 14, "NO": 15, "PL": 16,
    "CZ": 17, "EE": 18, "LV": 19, "LT": 20, "IE": 21, "IT": 22, "ES": 23, "PT": 24,
    "GR": 25, "RO": 26, "BG": 27, "HU": 28, "TR": 29, "IL": 30, "AE": 31, "ZA": 32,
    "BR": 33, "IN": 34, "MY": 35, "VN": 36, "TH": 37, "PH": 38, "ID": 39, "HK": 40,
    "KR": 41, "TW": 42, "RU": 99
}

COUNTRY_NAMES = {
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
    "KE": "Кения", "NZ": "Новая Зеландия",
    "HK": "Гонконг", "KR": "Южная Корея", "TW": "Тайвань",
    "EE": "Эстония", "LV": "Латвия", "LT": "Литва"
}

def get_config_id(config: str) -> str:
    protocol = get_protocol(config)
    host, port = extract_host_port(config)
    if not host or not port: return config
    return f"{protocol}@{host}:{port}"

def remove_duplicates(configs: List[str]) -> List[str]:
    seen, result, dups = {}, [], 0
    for cfg in configs:
        cid = get_config_id(cfg)
        if cid not in seen:
            seen[cid] = True
            result.append(cfg)
        else: dups += 1
    if dups > 0: print(f"  Removed duplicates: {dups}")
    return result

def process_config(config: str, reader) -> Optional[Tuple]:
    if not is_secure_config(config) or 'anycast' in config.lower():
        return None
    host, port = extract_host_port(config)
    if not host or not port: return None

    ping, is_working, used_xray, speed_mbps = verify_config(config, TIMEOUT)
    if not is_working or ping is None or ping > PING_MAX: return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    protocol = get_protocol(config)
    sni = (re.search(r'sni=([^&]+)', config) or [None, None]).group(1) or ""

    flag, country_code = get_country_geoip(host, reader)
    if country_code == "ZZ": flag, country_code = detect_country_by_domain(host)
    if host and host.lower().endswith('.ru') and country_code != "RU":
        flag, country_code = WHITE_FLAG, "??"
    if country_code == "ZZ" and not (host and host.lower().endswith('.ru')):
        flag, country_code = detect_country_from_name(name_part)
    if country_code == "ZZ" or flag == WHITE_FLAG: return None

    parts = []
    if sni and "cloudflare" in sni.lower(): parts.append("cloudflare")
    parts += [flag, COUNTRY_NAMES.get(country_code, country_code), "t.me/letovpn_free"]
    new_config = config.split('#', 1)[0] + '#' + ' '.join(parts)

    return (config, new_config, country_code, ping, (flag, protocol, ping, ping < PING_GOOD_THRESHOLD), speed_mbps)

def save_chunked_files(configs_list, base_name, chunk_size=200):
    total = len(configs_list)
    if total == 0: return
    i = 1
    while os.path.exists(f"{base_name}{i}.txt"): os.remove(f"{base_name}{i}.txt"); i += 1
    for i in range(0, total, chunk_size):
        chunk = configs_list[i:i+chunk_size]
        fn = i // chunk_size + 1
        with open(f"{base_name}{fn}.txt", "w", encoding="utf-8") as f:
            for cfg in chunk: f.write(cfg + "\n")
        print(f"  {base_name}{fn}.txt: {len(chunk)} configs")

def main():
    start_time = time.time()
    init_xray()
    if not SOURCES: print("No sources! Check sources.txt"); return

    bot = TelegramBot()
    download_geoip_db()
    reader = init_geoip_reader()

    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} configs")
        all_configs.extend(cfgs)

    all_configs = list(dict.fromkeys(all_configs))
    filtered = remove_duplicates(all_configs)
    filtered = [c for c in filtered if 'anycast' not in c.lower()]
    total_count = len(filtered)
    print(f"Total after dedup: {total_count}")

    # PASS 1
    print("\nPass 1: finding working configs...")
    first_results, checked, start_sent = [], 0, False
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(process_config, cfg, reader) for cfg in filtered]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: first_results.append(res)
            checked += 1
            if not start_sent: bot.send_start(); start_sent = True
            if checked % 50 == 0: print(f"  {checked}/{total_count}. Found {len(first_results)}")
    print(f"  Pass 1: {len(first_results)} working configs")

    # PASS 2 (double check)
    if first_results:
        originals = [r[0] for r in first_results]
        print(f"\nPass 2: rechecking {len(originals)} configs...")
        second_results, checked2 = [], 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(process_config, cfg, reader) for cfg in originals]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res: second_results.append(res)
                checked2 += 1
                if checked2 % 20 == 0: print(f"  {checked2}/{len(originals)}. Confirmed {len(second_results)}")
        print(f"  Pass 2: {len(second_results)} confirmed")
        passed = set(r[0] for r in second_results)
        results = [r for r in first_results if r[0] in passed]
        print(f"  Total after double check: {len(results)}/{len(first_results)}")
    else: results = []

    # SORT & SAVE
    ru_configs = [(r[1], r[3]) for r in results if r[2] == "RU"]
    other_configs = [(r[1], r[2], r[3]) for r in results if r[2] != "RU" and r[2] != "??"]
    other_configs.sort(key=lambda x: (COUNTRY_SORT_ORDER.get(x[1], 50), x[2]))
    ru_configs.sort(key=lambda x: x[1])

    fast_count = len([r for r in results if r[3] < PING_GOOD_THRESHOLD])
    bot.send_final(total_count, len(results), fast_count, time.time() - start_time)

    os.makedirs("protocols", exist_ok=True)
    pf = {"VLESS": [], "VMESS": [], "TROJAN": []}
    for r in results:
        if r[2] == "??": continue
        nc = r[1]
        if nc.startswith('vless://'): pf["VLESS"].append(nc)
        elif nc.startswith('vmess://'): pf["VMESS"].append(nc)
        elif nc.startswith('trojan://'): pf["TROJAN"].append(nc)

    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "adop1344-bot/LetoVPN_free")
    hdr = f"#announce: Updated: {now}, more at @LetoVPN_free!\n#support-url: https://t.me/@why_im_gay\n#profile-update-interval: 1\n\n"

    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{hdr}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs: f.write(cfg + "\n")
    print(f"  configs.txt: {len(other_configs)} configs")

    save_chunked_files([cfg for cfg, _, _ in other_configs], "configs", 200)

    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{hdr}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs: f.write(cfg + "\n")
    print(f"  ru.txt: {len(ru_configs)} configs")

    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs: f.write(cfg + "\n")
    print(f"  configs_hiddify.txt: {len(other_configs)} configs")

    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs: f.write(cfg + "\n")
    print(f"  ru_hiddify.txt: {len(ru_configs)} configs")

    for proto, cfgs in pf.items():
        if cfgs:
            with open(f"protocols/{proto}.txt", "w", encoding="utf-8") as f:
                f.write(f"{hdr}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{proto}.txt\n#profile-title: {proto} TG@LetoVPN_Free\n\n")
                for c in cfgs: f.write(c + "\n")

    print(f"\nDone! Time: {time.time() - start_time:.1f}s")
    if reader: reader.close()

if __name__ == "__main__":
    main()