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
    COUNTRY_FLAGS, KEYWORDS, CITIES, DOMAIN_MAP, SOURCES
)
from src.ping import verify_config, extract_host_port, get_protocol, init_xray
from src.tg import TelegramBot
from src.geo import (
    detect_country_by_domain, detect_country_from_name,
    get_country_geoip, detect_city_by_ip, get_domain_note
)

# Отключаем предупреждения
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Названия стран на русском
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
    "KE": "Кения", "NZ": "Новая Зеландия"
}

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
        print(f"Ошибка загрузки {url}: {e}")
        return []

def process_config(config: str, reader) -> Optional[Tuple[str, str, float, float, float]]:
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
        flag = "🏳️"
        country_code = "??"

    if country_code == "ZZ" and not is_ru_domain:
        flag, country_code = detect_country_from_name(name_part)

    if country_code == "ZZ" or flag == "🏳️":
        return None

    # Скорость
    speed_str = ""
    if speed_mbps is not None and speed_mbps > 1:
        speed_str = f"{speed_mbps:.0f}Mbps"

    country_name_ru = COUNTRY_NAMES.get(country_code, country_code)

    # Формируем новое название: 🇺🇸 США 45Mbps sni=ya.ru
    parts = [flag, country_name_ru]
    if speed_str:
        parts.append(speed_str)
    parts.append(f"sni={sni}" if sni else "sni=no-sni")

    new_name = ' '.join(parts)

    # Добавляем # перед new_name
    new_config = config.split('#', 1)[0] + '#' + new_name

    return (new_config, country_code, ping, ping, speed_mbps)


def main():
    start_time = time.time()

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
                results.append(res)

            checked += 1

            if not start_sent:
                bot.send_start()
                start_sent = True

            if checked % 100 == 0:
                print(f"Обработано {checked}/{len(filtered)}. Найдено {len(results)}")

    fast_count = len([r for r in results if r[2] < PING_GOOD_THRESHOLD])
    bot.send_final(len(filtered), len(results), fast_count, time.time() - start_time)

    # Разделяем на российские и остальные
    ru_configs = [(cfg, ping) for cfg, code, ping, _, _ in results if code == "RU"]
    other_configs = [(cfg, code, ping) for cfg, code, ping, _, _ in results if code != "RU" and code != "??"]

    other_configs.sort(key=lambda x: x[1])
    ru_configs.sort(key=lambda x: x[1])

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

    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")

    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n#profile-title: ru TG@LetoVPN_Free\n\n")
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")

    # Чистые файлы для Hiddify
    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _, _ in other_configs:
            f.write(cfg + "\n")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов")

    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for cfg, _ in ru_configs:
            f.write(cfg + "\n")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов")

    for protocol, configs in protocol_files.items():
        if configs:
            with open(f"protocols/{protocol}.txt", "w", encoding="utf-8") as f:
                f.write(f"{common_header}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{protocol}.txt\n#profile-title: {protocol} TG@LetoVPN_Free\n\n")
                for cfg in configs:
                    f.write(cfg + "\n")

    print(f"\nГотово!")
    print(f"  configs.txt: {len(other_configs)} конфигов")
    print(f"  configs_hiddify.txt: {len(other_configs)} конфигов (чистый)")
    print(f"  ru.txt: {len(ru_configs)} конфигов")
    print(f"  ru_hiddify.txt: {len(ru_configs)} конфигов (чистый)")

    if reader:
        reader.close()

if __name__ == "__main__":
    main()