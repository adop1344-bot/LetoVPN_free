#!/usr/bin/env python3
import requests
import concurrent.futures
import socket
import time
import base64
import json
import os
from datetime import datetime
from typing import List, Tuple, Optional

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
        name_part = ""

    # 3. Проверка CIDR-метки
    cidr_note = ""
    if '[*CIDR]' in name_part:
        cidr_note = " обход белых листов"

    # 4. TCP-пинг
    ping_ms = tcp_ping(host, port, TIMEOUT)
    if ping_ms is None:
        return None  # недоступен

    # 5. Добавляем ⚡ если пинг < 1000 мс
    lightning = "⚡" if ping_ms < PING_GOOD_THRESHOLD else ""

    # 6. Формируем новое название (без страны)
    #    формат: "#⚡ обход белых листов исходное_название"
    prefix = "#"
    if lightning:
        prefix += f"{lightning} "
    if cidr_note:
        prefix += f"{cidr_note} "
    
    # Убираем лишние пробелы в конце
    prefix = prefix.strip()
    
    # Добавляем исходное название, если оно есть
    if name_part:
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
