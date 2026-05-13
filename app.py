#!/usr/bin/env python3
import requests, concurrent.futures, socket, time, base64, json, os, re
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

# ----- Конфигурация -----
TIMEOUT = 3.0
MAX_WORKERS = 50
PING_GOOD_THRESHOLD = 200
PING_MAX = 10000
RETRY_PING = True

# ----- Загрузка внешних файлов -----
def load_sources() -> List[str]:
    with open("sources.txt") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

def load_flags() -> Tuple[dict, dict]:
    code_to_flag = {}
    with open("flags.txt") as f:
        for line in f:
            if ':' in line:
                k, v = line.strip().split(':', 1)
                code_to_flag[k] = v
    return code_to_flag, {v: k for k, v in code_to_flag.items()}

def load_keywords() -> dict:
    """Загружает ключевые слова из keywords.txt: код -> список слов"""
    keywords = {}
    with open("keywords.txt") as f:
        for line in f:
            if ':' in line:
                code, words_str = line.strip().split(':', 1)
                keywords[code] = [w.strip().lower() for w in words_str.split(',')]
    return keywords

def load_cities() -> dict:
    """Загружает маски IP из cities.txt: маска -> город"""
    cities = {}
    with open("cities.txt") as f:
        for line in f:
            if ':' in line:
                mask, city = line.strip().split(':', 1)
                cities[mask] = city
    return cities

COUNTRY_FLAGS, FLAG_TO_CODE = load_flags()
SOURCES = load_sources()
KEYWORDS = load_keywords()
CITIES = load_cities()

# ----- Основные функции -----
def detect_country_from_text(text: str) -> Tuple[str, str]:
    """Определяет страну, возвращает (флаг, код)"""
    lower = text.lower()
    # 1. Ищем флаг
    for flag in COUNTRY_FLAGS.values():
        if flag in text:
            return flag, FLAG_TO_CODE[flag]
    # 2. Ищем двухбуквенный код
    match = re.search(r'\b([A-Z]{2})\b', text)
    if match and match.group(1) in COUNTRY_FLAGS:
        code = match.group(1)
        return COUNTRY_FLAGS[code], code
    # 3. Ищем ключевые слова
    for code, words in KEYWORDS.items():
        for w in words:
            if w in lower:
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    # 4. Отдельные проверки для популярных стран
    if "russia" in lower or "россия" in lower:
        return COUNTRY_FLAGS.get("RU", "🇷🇺"), "RU"
    if "usa" in lower or "сша" in lower:
        return COUNTRY_FLAGS.get("US", "🇺🇸"), "US"
    return "🏳️", "ZZ"

def fetch_configs_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return [line.strip() for line in r.text.splitlines() 
                if line.strip() and not line.startswith('#')]
    except Exception as e:
        print(f"Ошибка {url}: {e}")
        return []

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    if config.startswith('vless://'):
        parts = config[8:].split('@')
        if len(parts) == 2:
            hostport = parts[1].split('?')[0].split('#')[0]
            if ':' in hostport:
                h, p = hostport.split(':', 1)
                try: return h, int(p)
                except: pass
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:] + '=' * (4 - len(config[8:]) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8'))
            return data.get('add'), int(data.get('port'))
        except: pass
    elif config.startswith('trojan://'):
        parts = config[9:].split('@')
        if len(parts) == 2:
            hostport = parts[1].split('?')[0].split('#')[0]
            if ':' in hostport:
                h, p = hostport.split(':', 1)
                try: return h, int(p)
                except: pass
    return None, None

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    try:
        s = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - s) * 1000
    except: return None

def check_config(host: str, port: int) -> Optional[float]:
    p1 = tcp_ping(host, port, TIMEOUT)
    if p1 is None: return None
    if RETRY_PING:
        time.sleep(0.5)
        p2 = tcp_ping(host, port, TIMEOUT)
        return min(p1, p2) if p2 is not None else p1
    return p1

def detect_city_by_ip(host: str) -> str:
    """Определяет город по маске IP из cities.txt"""
    if not re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return ""
    parts = host.split('.')
    if len(parts) < 2:
        return ""
    mask = f"{parts[0]}.{parts[1]}"
    return CITIES.get(mask, "")

def process_config(config: str) -> Optional[Tuple[str, str, float]]:
    if 'anycast' in config.lower(): 
        return None
    host, port = extract_host_port(config)
    if not host or not port: 
        return None
    ping = check_config(host, port)
    if ping is None or ping > PING_MAX: 
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    flag, code = detect_country_from_text(name_part)
    lightning = "⚡" if ping < PING_GOOD_THRESHOLD else ""
    city = detect_city_by_ip(host) if code == "RU" else ""
    cidr = " обход белых листов" if '[*CIDR]' in name_part else ""

    if code == "RU":
        parts = [f"#{flag}"]
        if lightning: 
            parts.append(lightning)
        if city: 
            parts.append(f"({city})")
        new_name = ''.join(parts) + cidr
    else:
        new_name = f"#{flag}{lightning}{cidr}"
    
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    new_config = config.split('#', 1)[0] + new_name if '#' in config else config + new_name
    return (new_config, code, ping)

def main():
    if not SOURCES:
        print("Нет источников! Проверьте sources.txt")
        return

    print("Загрузка конфигов...")
    all_cfg = []
    for url in SOURCES:
        cfg = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfg)}")
        all_cfg.extend(cfg)

    print(f"Всего: {len(all_cfg)}")
    all_cfg = list(dict.fromkeys(all_cfg))
    print(f"Уникальных: {len(all_cfg)}")
    filtered = [c for c in all_cfg if 'anycast' not in c.lower()]
    print(f"После anycast: {len(filtered)}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_config, cfg): cfg for cfg in filtered}
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res: 
                results.append(res)

    print(f"Работоспособных: {len(results)}")

    ru = [(cfg, ping) for cfg, code, ping in results if code == "RU"]
    other = [(cfg, code, ping) for cfg, code, ping in results if code != "RU"]
    other.sort(key=lambda x: x[1])
    ru.sort(key=lambda x: x[1])

    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_USERNAME/YOUR_REPO")
    common_header = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""

    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other:
            f.write(cfg + "\n")

    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru:
            f.write(cfg + "\n")

    print(f"Готово! configs.txt ({len(other)}), ru.txt ({len(ru)})")

if __name__ == "__main__":
    main()
