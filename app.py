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
SOURCES = [
    "https://raw.githubusercontent.com/GoldCaviar/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt",
    "https://github.com/terik21/HiddifySubs-VlessKeys/raw/refs/heads/main/WhiteKeys",
    "https://github.com/terik21/HiddifySubs-VlessKeys/raw/refs/heads/main/RU_other",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/26.txt",
    "https://raw.githubusercontent.com/luxxuria/harvester/refs/heads/main/top_600.txt"
]
TIMEOUT = 3.0
MAX_WORKERS = 30
PING_GOOD_THRESHOLD = 1000

# ----- Страны и их флаги -----
FLAG_BY_CODE = {
    "RU": "🇷🇺", "UA": "🇺🇦", "BY": "🇧🇾", "KZ": "🇰🇿",
    "US": "🇺🇸", "CA": "🇨🇦", "MX": "🇲🇽",
    "DE": "🇩🇪", "FR": "🇫🇷", "GB": "🇬🇧", "IT": "🇮🇹", "ES": "🇪🇸",
    "NL": "🇳🇱", "PL": "🇵🇱", "SE": "🇸🇪", "NO": "🇳🇴", "FI": "🇫🇮",
    "DK": "🇩🇰", "BE": "🇧🇪", "CH": "🇨🇭", "AT": "🇦🇹", "CZ": "🇨🇿",
    "HU": "🇭🇺", "RO": "🇷🇴", "BG": "🇧🇬", "GR": "🇬🇷", "PT": "🇵🇹",
    "IE": "🇮🇪", "IS": "🇮🇸", "LT": "🇱🇹", "LV": "🇱🇻", "EE": "🇪🇪",
    "JP": "🇯🇵", "KR": "🇰🇷", "CN": "🇨🇳", "TW": "🇹🇼", "HK": "🇭🇰",
    "SG": "🇸🇬", "IN": "🇮🇳", "ID": "🇮🇩", "MY": "🇲🇾", "TH": "🇹🇭",
    "VN": "🇻🇳", "PH": "🇵🇭", "TR": "🇹🇷", "IL": "🇮🇱", "SA": "🇸🇦",
    "AE": "🇦🇪", "BR": "🇧🇷", "AR": "🇦🇷", "CL": "🇨🇱", "CO": "🇨🇴",
    "AU": "🇦🇺", "NZ": "🇳🇿", "ZA": "🇿🇦"
}

def detect_country_by_name(name: str) -> Tuple[str, str]:
    """Определяет страну по названию, возвращает (флаг, код_страны)"""
    # Ищем флаг
    for code, flag in FLAG_BY_CODE.items():
        if flag in name:
            return (flag, code)
    # Ищем код страны
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match:
        code = match.group(1)
        if code in FLAG_BY_CODE:
            return (FLAG_BY_CODE[code], code)
    # Ищем названия
    country_names = {
        "россия": ("🇷🇺", "RU"), "russia": ("🇷🇺", "RU"), "ru": ("🇷🇺", "RU"),
        "сша": ("🇺🇸", "US"), "usa": ("🇺🇸", "US"), "us": ("🇺🇸", "US"),
        "германия": ("🇩🇪", "DE"), "germany": ("🇩🇪", "DE"), "de": ("🇩🇪", "DE"),
        "франция": ("🇫🇷", "FR"), "france": ("🇫🇷", "FR"),
        "нидерланды": ("🇳🇱", "NL"), "netherlands": ("🇳🇱", "NL")
    }
    name_lower = name.lower()
    for key, (flag, code) in country_names.items():
        if key in name_lower:
            return (flag, code)
    return ("🏳️", "ZZ")

def fetch_configs_from_url(url: str) -> List[str]:
    """Загружает конфиги из URL"""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        lines = r.text.splitlines()
        configs = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            configs.append(line)
        return configs
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return []

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    """Извлекает хост и порт из конфига"""
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
            decoded = base64.b64decode(b64).decode('utf-8')
            data = json.loads(decoded)
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
    """Проверяет доступность хоста:порта"""
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.time() - start) * 1000
        return elapsed
    except:
        return None

def process_config(config: str) -> Optional[Tuple[str, str, float]]:
    """
    Тестирует конфиг.
    Возвращает (новый_конфиг, код_страны, пинг) или None
    """
    # Пропуск anycast
    if 'anycast' in config.lower():
        return None

    # Извлечение хоста и порта
    host, port = extract_host_port(config)
    if not host or not port:
        return None

    # Извлечение названия
    name_part = ""
    if '#' in config:
        name_part = config.split('#', 1)[1].strip()
    else:
        name_part = ""

    # TCP-пинг
    ping_ms = tcp_ping(host, port, TIMEOUT)
    if ping_ms is None:
        return None

    # Определение страны
    flag, country_code = detect_country_by_name(name_part)
    
    # Молния если пинг хороший
    lightning = "⚡" if ping_ms < PING_GOOD_THRESHOLD else ""

    # Проверка CIDR-метки
    cidr_note = " обход белых листов" if '[*CIDR]' in name_part else ""

    # Формирование нового названия (без флага России!)
    # Для всех стран, включая Россию, убираем флаг из названия
    prefix = "#"
    if lightning:
        prefix += f" {lightning}"
    if cidr_note:
        prefix += f"{cidr_note}"
    
    if name_part:
        # Убираем флаг из оригинального названия, если он там был
        clean_name = name_part
        for code, f in FLAG_BY_CODE.items():
            if f in clean_name:
                clean_name = clean_name.replace(f, "").strip()
        new_name = f"{prefix} {clean_name}"
    else:
        new_name = prefix

    # Сборка итогового конфига
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name

    return (new_config, country_code, ping_ms)

def main():
    print("Загрузка конфигов из источников...")
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)

    print(f"Всего получено: {len(all_configs)}")
    
    # Удаление дубликатов
    all_configs = list(dict.fromkeys(all_configs))
    print(f"После удаления дублей: {len(all_configs)}")

    # Фильтрация anycast
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    print(f"После пропуска anycast: {len(filtered)}")

    # Многопоточное тестирование
    results = []  # (config, country_code, ping)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_config = {executor.submit(process_config, cfg): cfg for cfg in filtered}
        for future in concurrent.futures.as_completed(future_to_config):
            res = future.result()
            if res is not None:
                results.append(res)

    print(f"Работоспособных конфигов: {len(results)}")
    
    # Разделяем на российские и остальные
    ru_configs = []      # только Россия
    other_configs = []   # все остальные страны
    
    for config, country_code, ping in results:
        if country_code == "RU":
            ru_configs.append((config, ping))
        else:
            other_configs.append((config, country_code, ping))
    
    # Сортируем остальные по странам
    other_configs.sort(key=lambda x: x[1])
    
    # Сортируем российские по пингу (для ru.txt)
    ru_configs.sort(key=lambda x: x[1])
    
    # Создаём заголовки
    moscow_tz = timezone(timedelta(hours=3))
    now = datetime.now(moscow_tz).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_USERNAME/YOUR_REPO")
    this_url = f"https://raw.githubusercontent.com/{repo}/main/configs.txt"
    ru_url = f"https://raw.githubusercontent.com/{repo}/main/ru.txt"
    
    # Заголовок для configs.txt (без России)
    header_configs = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#profile-web-page-url: {this_url}
#profile-title: TG@LetoVPN_Free
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    # Заголовок для ru.txt (только Россия)
    header_ru = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#profile-web-page-url: {ru_url}
#profile-title: Russia TG@LetoVPN_Free
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    
    # Сохраняем configs.txt (все конфиги КРОМЕ России)
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(header_configs)
        for config, _, _ in other_configs:
            f.write(config + "\n")
    
    # Сохраняем ru.txt (только Россия, отсортированные по пингу)
    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(header_ru)
        for config, _ in ru_configs:
            f.write(config + "\n")
    
    print(f"Готово! configs.txt ({len(other_configs)} конфигов без 🇷🇺) и ru.txt ({len(ru_configs)} российских конфигов) сохранены.")

if __name__ == "__main__":
    main()
