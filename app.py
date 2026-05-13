#!/usr/bin/env python3
import requests
import concurrent.futures
import socket
import time
import base64
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

# ----- Конфигурация -----
TIMEOUT = 3.0
MAX_WORKERS = 30
PING_GOOD_THRESHOLD = 200    # мс — ставим ⚡
PING_MAX = 10000             # мс — отбрасывать конфиги с пингом выше
RETRY_PING = True

def load_sources() -> List[str]:
    with open("sources.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

def load_flags() -> Tuple[dict, dict]:
    code_to_flag = {}
    with open("flags.txt", "r", encoding="utf-8") as f:
        for line in f:
            if ':' in line:
                code, flag = line.strip().split(':', 1)
                code_to_flag[code] = flag
    flag_to_code = {v: k for k, v in code_to_flag.items()}
    return code_to_flag, flag_to_code

# ----- Определение города по IP (для России) -----
def detect_city_by_ip(host: str) -> str:
    """Определяет город по первым октетам IP-адреса"""
    if not host or not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
        return ""
    
    parts = host.split('.')
    if len(parts) != 4:
        return ""
    
    a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
    
    # Диапазоны IP для российских городов
    # Москва
    if (a == 5 and 45 <= b <= 255) or \
       (a == 31 and 13 <= b <= 173) or \
       (a == 37) or \
       (a == 46 and 0 <= b <= 63) or \
       (a == 62 and 105 <= b <= 205) or \
       (a == 80 and 68 <= b <= 95) or \
       (a == 81 and 1 <= b <= 30) or \
       (a == 85 and 17 <= b <= 118) or \
       (a == 89 and 22 <= b <= 253) or \
       (a == 91 and 76 <= b <= 227) or \
       (a == 93 and 80 <= b <= 184) or \
       (a == 94 and 25 <= b <= 50) or \
       (a == 95 and 25 <= b <= 215) or \
       (a == 109 and 60 <= b <= 252) or \
       (a == 128 and 74 <= b <= 204) or \
       (a == 130 and 193 <= b <= 255) or \
       (a == 176 and 9 <= b <= 124) or \
       (a == 178 and 17 <= b <= 219) or \
       (a == 185 and 1 <= b <= 242) or \
       (a == 188 and 16 <= b <= 167) or \
       (a == 193 and 19 <= b <= 232) or \
       (a == 194 and 4 <= b <= 186) or \
       (a == 195 and 34 <= b <= 239) or \
       (a == 212 and 16 <= b <= 112) or \
       (a == 217 and 29 <= b <= 118):
        return "Москва"
    
    # Санкт-Петербург
    if (a == 5 and 200 <= b <= 227) or \
       (a == 31 and 41 <= b <= 162) or \
       (a == 46 and 160 <= b <= 183) or \
       (a == 80 and 250 <= b <= 255) or \
       (a == 81 and 4 <= b <= 9) or \
       (a == 85 and 249 <= b <= 255) or \
       (a == 87 and 251 <= b <= 255) or \
       (a == 91 and 250 <= b <= 255) or \
       (a == 95 and 164 <= b <= 168) or \
       (a == 95 and 220 <= b <= 229) or \
       (a == 109 and 126 <= b <= 126) or \
       (a == 128 and 205 <= b <= 205) or \
       (a == 176 and 239 <= b <= 239) or \
       (a == 178 and 71 <= b <= 72) or \
       (a == 178 and 247 <= b <= 248) or \
       (a == 185 and 246 <= b <= 246) or \
       (a == 193 and 192 <= b <= 193) or \
       (a == 195 and 162 <= b <= 162) or \
       (a == 212 and 233 <= b <= 233) or \
       (a == 213 and 106 <= b <= 106) or \
       (a == 217 and 118 <= b <= 118):
        return "СПб"
    
    # Новосибирск
    if (a == 5 and 188 <= b <= 191) or \
       (a == 46 and 170 <= b <= 173) or \
       (a == 82 and 140 <= b <= 159) or \
       (a == 92 and 248 <= b <= 255) or \
       (a == 95 and 154 <= b <= 182) or \
       (a == 176 and 105 <= b <= 110) or \
       (a == 178 and 186 <= b <= 189) or \
       (a == 185 and 64 <= b <= 65) or \
       (a == 188 and 233 <= b <= 234) or \
       (a == 193 and 242 <= b <= 242):
        return "Новосибирск"
    
    # Екатеринбург
    if (a == 5 and 191 <= b <= 191) or \
       (a == 31 and 130 <= b <= 130) or \
       (a == 46 and 20 <= b <= 21) or \
       (a == 80 and 64 <= b <= 64) or \
       (a == 82 and 209 <= b <= 209) or \
       (a == 82 and 77 <= b <= 77) or \
       (a == 91 and 216 <= b <= 216) or \
       (a == 94 and 246 <= b <= 246) or \
       (a == 95 and 144 <= b <= 144) or \
       (a == 176 and 194 <= b <= 194) or \
       (a == 178 and 178 <= b <= 178) or \
       (a == 185 and 204 <= b <= 204) or \
       (a == 193 and 203 <= b <= 203):
        return "Екатеринбург"
    
    # Казань
    if (a == 5 and 185 <= b <= 185) or \
       (a == 31 and 163 <= b <= 163) or \
       (a == 46 and 42 <= b <= 44) or \
       (a == 78 and 85 <= b <= 85) or \
       (a == 85 and 49 <= b <= 49) or \
       (a == 90 and 98 <= b <= 98) or \
       (a == 92 and 247 <= b <= 247) or \
       (a == 95 and 97 <= b <= 97) or \
       (a == 95 and 250 <= b <= 250) or \
       (a == 176 and 124 <= b <= 124) or \
       (a == 178 and 168 <= b <= 168) or \
       (a == 185 and 3 <= b <= 3) or \
       (a == 188 and 236 <= b <= 236) or \
       (a == 193 and 201 <= b <= 201):
        return "Казань"
    
    # Нижний Новгород
    if (a == 5 and 43 <= b <= 44) or \
       (a == 31 and 134 <= b <= 134) or \
       (a == 46 and 171 <= b <= 172) or \
       (a == 77 and 83 <= b <= 83) or \
       (a == 85 and 92 <= b <= 92) or \
       (a == 91 and 184 <= b <= 184) or \
       (a == 95 and 37 <= b <= 37) or \
       (a == 176 and 104 <= b <= 104) or \
       (a == 178 and 122 <= b <= 122) or \
       (a == 185 and 221 <= b <= 221) or \
       (a == 193 and 219 <= b <= 219) or \
       (a == 213 and 204 <= b <= 204):
        return "Н.Новгород"
    
    # Самара
    if (a == 5 and 31 <= b <= 32) or \
       (a == 31 and 17 <= b <= 17) or \
       (a == 46 and 0 <= b <= 0) or \
       (a == 81 and 56 <= b <= 56) or \
       (a == 95 and 139 <= b <= 139) or \
       (a == 176 and 57 <= b <= 57) or \
       (a == 185 and 57 <= b <= 57) or \
       (a == 188 and 72 <= b <= 72) or \
       (a == 213 and 226 <= b <= 226):
        return "Самара"
    
    # Ростов-на-Дону
    if (a == 5 and 198 <= b <= 198) or \
       (a == 46 and 28 <= b <= 28) or \
       (a == 81 and 28 <= b <= 28) or \
       (a == 95 and 64 <= b <= 64) or \
       (a == 176 and 194 <= b <= 194) or \
       (a == 185 and 37 <= b <= 37) or \
       (a == 188 and 187 <= b <= 187) or \
       (a == 194 and 184 <= b <= 184):
        return "Ростов-на-Дону"
    
    # Челябинск
    if (a == 5 and 188 <= b <= 188) or \
       (a == 31 and 130 <= b <= 130) or \
       (a == 81 and 0 <= b <= 0) or \
       (a == 95 and 79 <= b <= 79) or \
       (a == 178 and 91 <= b <= 91) or \
       (a == 185 and 19 <= b <= 19):
        return "Челябинск"
    
    # Владивосток
    if (a == 5 and 97 <= b <= 97) or \
       (a == 31 and 192 <= b <= 192) or \
       (a == 85 and 248 <= b <= 248) or \
       (a == 89 and 230 <= b <= 230) or \
       (a == 95 and 215 <= b <= 215) or \
       (a == 176 and 96 <= b <= 96) or \
       (a == 185 and 114 <= b <= 114) or \
       (a == 188 and 35 <= b <= 35):
        return "Владивосток"
    
    # Красноярск
    if (a == 5 and 210 <= b <= 210) or \
       (a == 31 and 62 <= b <= 62) or \
       (a == 80 and 85 <= b <= 85) or \
       (a == 95 and 38 <= b <= 38) or \
       (a == 176 and 227 <= b <= 227) or \
       (a == 185 and 120 <= b <= 120):
        return "Красноярск"
    
    # Остальные города (менее точные диапазоны)
    if (a == 5 and 46 <= b <= 46):
        return "Тверь"
    if (a == 31 and 45 <= b <= 45):
        return "Краснодар"
    if (a == 46 and 140 <= b <= 140):
        return "Воронеж"
    if (a == 81 and 177 <= b <= 177):
        return "Иркутск"
    if (a == 92 and 63 <= b <= 63):
        return "Тюмень"
    if (a == 95 and 159 <= b <= 159):
        return "Пермь"
    if (a == 176 and 107 <= b <= 107):
        return "Омск"
    if (a == 178 and 213 <= b <= 213):
        return "Саратов"
    if (a == 185 and 210 <= b <= 210):
        return "Барнаул"
    
    return ""

COUNTRY_FLAGS, FLAG_TO_CODE = load_flags()
SOURCES = load_sources()

def detect_country_from_text(text: str) -> Tuple[str, str]:
    """Определяет страну, возвращает (флаг, код)"""
    for flag in COUNTRY_FLAGS.values():
        if flag in text:
            code = FLAG_TO_CODE.get(flag, "ZZ")
            return flag, code
    match = re.search(r'\b([A-Z]{2})\b', text)
    if match and match.group(1) in COUNTRY_FLAGS:
        code = match.group(1)
        return COUNTRY_FLAGS[code], code
    lower = text.lower()
    if "russia" in lower or "россия" in lower:
        return COUNTRY_FLAGS.get("RU", "🇷🇺"), "RU"
    return "🏳️", "ZZ"

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
        parts = config[8:].split('@')
        if len(parts) == 2:
            hostport = parts[1].split('?')[0].split('#')[0]
            if ':' in hostport:
                host, port_str = hostport.split(':', 1)
                try:
                    return host, int(port_str)
                except:
                    pass
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:]
            b64 += '=' * (4 - len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8'))
            host = data.get('add')
            port = data.get('port')
            if host and port:
                return host, int(port)
        except:
            pass
    elif config.startswith('trojan://'):
        parts = config[9:].split('@')
        if len(parts) == 2:
            hostport = parts[1].split('?')[0].split('#')[0]
            if ':' in hostport:
                host, port_str = hostport.split(':', 1)
                try:
                    return host, int(port_str)
                except:
                    pass
    return None, None

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def check_config(host: str, port: int) -> Optional[float]:
    """Проверяет конфиг, возможно с повторным пингом"""
    ping1 = tcp_ping(host, port, TIMEOUT)
    if ping1 is None:
        return None
    if RETRY_PING:
        time.sleep(0.5)
        ping2 = tcp_ping(host, port, TIMEOUT)
        if ping2 is not None:
            return min(ping1, ping2)
    return ping1

def process_config(config: str) -> Optional[Tuple[str, str, float]]:
    """Тестирует конфиг. Возвращает (конфиг, код_страны, пинг)"""
    if 'anycast' in config.lower():
        return None

    host, port = extract_host_port(config)
    if not host or not port:
        return None

    ping_ms = check_config(host, port)
    if ping_ms is None or ping_ms > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    flag, country_code = detect_country_from_text(name_part)
    
    # Молния если пинг хороший
    lightning = "⚡" if ping_ms < PING_GOOD_THRESHOLD else ""
    
    # Определяем город для российских конфигов
    city = ""
    if country_code == "RU":
        city = detect_city_by_ip(host)
    
    # Формируем название: #🇷🇺⚡(город) или #🇷🇺(город) или просто #🇷🇺
    if country_code == "RU":
        if lightning and city:
            new_name = f"#{flag}{lightning}({city})"
        elif lightning:
            new_name = f"#{flag}{lightning}"
        elif city:
            new_name = f"#{flag}({city})"
        else:
            new_name = f"#{flag}"
    else:
        # Для других стран — без города
        new_name = f"#{flag}"
        if lightning:
            new_name += f"{lightning}"
    
    # Добавляем CIDR-метку, если есть
    if '[*CIDR]' in name_part:
        new_name += " обход белых листов"
    
    # Собираем итоговый конфиг
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name

    return (new_config, country_code, ping_ms)

def main():
    if not SOURCES:
        print("Нет источников! Проверьте файл sources.txt")
        return

    print("Загрузка конфигов из источников...")
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)

    print(f"Всего получено: {len(all_configs)}")
    all_configs = list(dict.fromkeys(all_configs))
    print(f"После удаления дублей: {len(all_configs)}")

    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    print(f"После пропуска anycast: {len(filtered)}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_config = {executor.submit(process_config, cfg): cfg for cfg in filtered}
        for future in concurrent.futures.as_completed(future_to_config):
            res = future.result()
            if res is not None:
                results.append(res)

    print(f"Работоспособных конфигов: {len(results)}")

    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping in results if code != "RU"]

    other_configs.sort(key=lambda x: x[1])
    ru_configs.sort(key=lambda x: x[1])

    moscow_tz = timezone(timedelta(hours=3))
    now = datetime.now(moscow_tz).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_USERNAME/YOUR_REPO")

    common_header = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""

    # configs.txt (все, кроме России)
    this_url = f"https://raw.githubusercontent.com/{repo}/main/configs.txt"
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: {this_url}\n#profile-title: TG@LetoVPN_Free\n\n")
        for config, _, _ in other_configs:
            f.write(config + "\n")

    # ru.txt (только Россия)
    ru_url = f"https://raw.githubusercontent.com/{repo}/main/ru.txt"
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: {ru_url}\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for config, _ in ru_configs:
            f.write(config + "\n")

    print(f"Готово! configs.txt ({len(other_configs)}), ru.txt ({len(ru_configs)})")

if __name__ == "__main__":
    main()
