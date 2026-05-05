#!/usr/bin/env python3
import requests
import concurrent.futures
import socket
import time
import re
import base64
import json
import os
from urllib.parse import urlparse, unquote
from datetime import datetime
from typing import List, Tuple, Optional, Dict

# ----- Конфигурация -----
SOURCES = [
    "https://raw.githubusercontent.com/GoldCaviar/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt",
    "https://github.com/terik21/HiddifySubs-VlessKeys/raw/refs/heads/main/WhiteKeys",
    "https://github.com/terik21/HiddifySubs-VlessKeys/raw/refs/heads/main/RU_other"
]
TIMEOUT = 3.0          # таймаут теста в секундах
MAX_WORKERS = 30       # число потоков
PING_GOOD_THRESHOLD = 1000  # мс, ниже этой границы ставим ⚡

# Маппинг: ключ (код страны или флаг) -> (флаг, русское название)
COUNTRY_MAP = {
    # Европа
    "RU": ("🇷🇺", "Россия"),
    "UA": ("🇺🇦", "Украина"),
    "BY": ("🇧🇾", "Беларусь"),
    "KZ": ("🇰🇿", "Казахстан"),
    "DE": ("🇩🇪", "Германия"),
    "FR": ("🇫🇷", "Франция"),
    "GB": ("🇬🇧", "Великобритания"),
    "IT": ("🇮🇹", "Италия"),
    "ES": ("🇪🇸", "Испания"),
    "NL": ("🇳🇱", "Нидерланды"),
    "PL": ("🇵🇱", "Польша"),
    "SE": ("🇸🇪", "Швеция"),
    "NO": ("🇳🇴", "Норвегия"),
    "FI": ("🇫🇮", "Финляндия"),
    "DK": ("🇩🇰", "Дания"),
    "BE": ("🇧🇪", "Бельгия"),
    "CH": ("🇨🇭", "Швейцария"),
    "AT": ("🇦🇹", "Австрия"),
    "CZ": ("🇨🇿", "Чехия"),
    "HU": ("🇭🇺", "Венгрия"),
    "RO": ("🇷🇴", "Румыния"),
    "BG": ("🇧🇬", "Болгария"),
    "GR": ("🇬🇷", "Греция"),
    "PT": ("🇵🇹", "Португалия"),
    "IE": ("🇮🇪", "Ирландия"),
    "IS": ("🇮🇸", "Исландия"),
    "LT": ("🇱🇹", "Литва"),
    "LV": ("🇱🇻", "Латвия"),
    "EE": ("🇪🇪", "Эстония"),
    
    # Азия
    "JP": ("🇯🇵", "Япония"),
    "KR": ("🇰🇷", "Южная Корея"),
    "CN": ("🇨🇳", "Китай"),
    "TW": ("🇹🇼", "Тайвань"),
    "HK": ("🇭🇰", "Гонконг"),
    "SG": ("🇸🇬", "Сингапур"),
    "IN": ("🇮🇳", "Индия"),
    "ID": ("🇮🇩", "Индонезия"),
    "MY": ("🇲🇾", "Малайзия"),
    "TH": ("🇹🇭", "Таиланд"),
    "VN": ("🇻🇳", "Вьетнам"),
    "PH": ("🇵🇭", "Филиппины"),
    "PK": ("🇵🇰", "Пакистан"),
    "BD": ("🇧🇩", "Бангладеш"),
    "TR": ("🇹🇷", "Турция"),
    "IL": ("🇮🇱", "Израиль"),
    "SA": ("🇸🇦", "Саудовская Аравия"),
    "AE": ("🇦🇪", "ОАЭ"),
    "QA": ("🇶🇦", "Катар"),
    "KW": ("🇰🇼", "Кувейт"),
    
    # Северная Америка
    "US": ("🇺🇸", "США"),
    "CA": ("🇨🇦", "Канада"),
    "MX": ("🇲🇽", "Мексика"),
    
    # Южная Америка
    "BR": ("🇧🇷", "Бразилия"),
    "AR": ("🇦🇷", "Аргентина"),
    "CL": ("🇨🇱", "Чили"),
    "CO": ("🇨🇴", "Колумбия"),
    "PE": ("🇵🇪", "Перу"),
    "VE": ("🇻🇪", "Венесуэла"),
    
    # Африка
    "ZA": ("🇿🇦", "ЮАР"),
    "EG": ("🇪🇬", "Египет"),
    "NG": ("🇳🇬", "Нигерия"),
    "MA": ("🇲🇦", "Марокко"),
    "KE": ("🇰🇪", "Кения"),
    
    # Австралия и Океания
    "AU": ("🇦🇺", "Австралия"),
    "NZ": ("🇳🇿", "Новая Зеландия"),
}

# Автоматическое преобразование флагов в коды
FLAG_TO_CODE = {
    "🇷🇺": "RU", "🇺🇦": "UA", "🇧🇾": "BY", "🇰🇿": "KZ",
    "🇺🇸": "US", "🇨🇦": "CA", "🇲🇽": "MX",
    "🇩🇪": "DE", "🇫🇷": "FR", "🇬🇧": "GB", "🇮🇹": "IT", "🇪🇸": "ES",
    "🇳🇱": "NL", "🇵🇱": "PL", "🇸🇪": "SE", "🇳🇴": "NO", "🇫🇮": "FI",
    "🇩🇰": "DK", "🇧🇪": "BE", "🇨🇭": "CH", "🇦🇹": "AT", "🇨🇿": "CZ",
    "🇭🇺": "HU", "🇷🇴": "RO", "🇧🇬": "BG", "🇬🇷": "GR", "🇵🇹": "PT",
    "🇮🇪": "IE", "🇮🇸": "IS", "🇱🇹": "LT", "🇱🇻": "LV", "🇪🇪": "EE",
    "🇯🇵": "JP", "🇰🇷": "KR", "🇨🇳": "CN", "🇹🇼": "TW", "🇭🇰": "HK",
    "🇸🇬": "SG", "🇮🇳": "IN", "🇮🇩": "ID", "🇲🇾": "MY", "🇹🇭": "TH",
    "🇻🇳": "VN", "🇵🇭": "PH", "🇵🇰": "PK", "🇧🇩": "BD", "🇹🇷": "TR",
    "🇮🇱": "IL", "🇸🇦": "SA", "🇦🇪": "AE", "🇶🇦": "QA", "🇰🇼": "KW",
    "🇧🇷": "BR", "🇦🇷": "AR", "🇨🇱": "CL", "🇨🇴": "CO", "🇵🇪": "PE",
    "🇻🇪": "VE", "🇿🇦": "ZA", "🇪🇬": "EG", "🇳🇬": "NG", "🇲🇦": "MA",
    "🇰🇪": "KE", "🇦🇺": "AU", "🇳🇿": "NZ",
}

# ----- Вспомогательные функции -----
def fetch_configs_from_url(url: str) -> List[str]:
    """Загружает строки из URL, фильтрует пустые и комментарии (#)"""
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
    """Извлекает хост и порт из строки vless://, vmess://, trojan:// и т.д."""
    # vless://uuid@host:port?params#name
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
    # vmess://base64
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:]
            # добавим паддинг
            b64 += '=' * (4 - len(b64) % 4)
            decoded = base64.b64decode(b64).decode('utf-8')
            data = json.loads(decoded)
            host = data.get('add')
            port = data.get('port')
            if host and port:
                return host, int(port)
        except:
            pass
    # trojan://password@host:port?params#name
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
    # shadowsocks://... (необязательно)
    return None, None

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    """Возвращает время установки соединения в мс или None, если не удалось"""
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.time() - start) * 1000
        return elapsed
    except:
        return None

def detect_country_from_name(name: str) -> Tuple[str, str]:
    """Возвращает (флаг, русское название) на основе имени конфига"""
    # Сначала ищем эмодзи флага
    for flag, code in FLAG_TO_CODE.items():
        if flag in name:
            if code in COUNTRY_MAP:
                return COUNTRY_MAP[code]
            else:
                return flag, code  # fallback
    # Ищем двухбуквенный код (RU, US и т.д.)
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match:
        code = match.group(1)
        if code in COUNTRY_MAP:
            return COUNTRY_MAP[code]
    # Если ничего не нашли, возвращаем заглушку
    return "🏳️", "Unknown"

def process_config(config: str) -> Optional[str]:
    """
    Тестирует один конфиг.
    Возвращает строку для итогового файла или None, если конфиг не прошёл.
    """
    # 1. Пропуск anycast
    if 'anycast' in config.lower():
        return None

    # 2. Извлечение хоста, порта и названия
    host, port = extract_host_port(config)
    if not host or not port:
        return None

    # Извлечение названия (часть после #)
    name_part = ""
    if '#' in config:
        name_part = config.split('#', 1)[1].strip()
    else:
        name_part = "no_name"

    # 3. Проверка CIDR-метки
    cidr_note = ""
    if '[*CIDR]' in name_part:
        cidr_note = " обход белых листов"

    # 4. Определение страны
    flag, country_ru = detect_country_from_name(name_part)

    # 5. TCP-пинг
    ping_ms = tcp_ping(host, port, TIMEOUT)
    if ping_ms is None:
        return None  # недоступен

    # 6. Добавляем ⚡ если пинг < 1000 мс
    lightning = "⚡" if ping_ms < PING_GOOD_THRESHOLD else ""

    # 7. Формируем новое название
    #    формат: "#🇷🇺 Россия⚡ обход белых листов исходное_название"
    prefix = f"#{flag} {country_ru}"
    if lightning:
        prefix += f" {lightning}"
    if cidr_note:
        prefix += f" {cidr_note}"
    # добавим пробел перед исходным названием, если оно не пустое
    if name_part and name_part != "no_name":
        new_name = f"{prefix} {name_part}"
    else:
        new_name = prefix

    # Заменяем старую часть #... на новую
    if '#' in config:
        new_config = config.split('#', 1)[0] + new_name
    else:
        new_config = config + new_name

    return new_config

def main():
    print("Загрузка конфигов из источников...")
    all_configs = []
    for url in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} конфигов")
        all_configs.extend(cfgs)

    print(f"Всего получено: {len(all_configs)}")
    # Удаляем дубликаты (по строке)
    all_configs = list(dict.fromkeys(all_configs))
    print(f"После удаления дублей: {len(all_configs)}")

    # Применяем фильтр anycast до многопоточности (быстро)
    filtered = [c for c in all_configs if 'anycast' not in c.lower()]
    print(f"После пропуска anycast: {len(filtered)}")

    # Многопоточное тестирование
    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_config = {executor.submit(process_config, cfg): cfg for cfg in filtered}
        for future in concurrent.futures.as_completed(future_to_config):
            res = future.result()
            if res is not None:
                working.append(res)

    print(f"Работоспособных конфигов: {len(working)}")

    # Генерация заголовка
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    # Автоматическое определение URL репозитория
    repo = os.getenv("GITHUB_REPOSITORY", "YOUR_USERNAME/YOUR_REPO")
    this_url = f"https://raw.githubusercontent.com/{repo}/main/configs.txt"
    
    header = f"""#announce: Обновлено: {now}, больше в телеграм канале @LetoVPN_free! Обновляется каждый +- час
#profile-web-page-url: {this_url}
#profile-title: TG@LetoVPN_Free
#support-url: https://t.me/@why_im_gay
#profile-update-interval: 1

"""
    # Сохраняем результат
    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(header)
        for line in working:
            f.write(line + "\n")

    print("Готово! configs.txt сохранён.")

if __name__ == "__main__":
    main()
