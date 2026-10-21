#!/usr/bin/env python3
import concurrent.futures
import os
import re
import time
import warnings
import urllib3
import requests
from datetime import datetime, timezone, timedelta

from src.config import (
    TIMEOUT, MAX_WORKERS, PING_GOOD_THRESHOLD, PING_MAX, load_sources)
from src.geo import (
    WHITE_FLAG, COUNTRY_FLAGS, download_geoip_db, init_geoip_reader,
    detect_country, detect_city_by_ip, resolve_host, is_private_host)
from src.ping import verify_config, extract_host_port, get_protocol, init_xray
from src.tg import TelegramBot

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SOURCES = load_sources()

COUNTRY_SORT_ORDER = {"NL":0,"DE":1,"FI":2,"US":3,"GB":4,"FR":5,"SG":6,"CA":7,"JP":8,
    "AU":9,"CH":10,"AT":11,"BE":12,"DK":13,"SE":14,"NO":15,"PL":16,"CZ":17,
    "EE":18,"LV":19,"LT":20,"IE":21,"IT":22,"ES":23,"PT":24,"GR":25,"RO":26,
    "BG":27,"HU":28,"TR":29,"IL":30,"AE":31,"ZA":32,"BR":33,"IN":34,"MY":35,
    "VN":36,"TH":37,"PH":38,"ID":39,"HK":40,"KR":41,"TW":42,"RU":99}

COUNTRY_NAMES = {"RU":"Россия","US":"США","DE":"Германия","FR":"Франция","NL":"Нидерланды",
    "GB":"Великобритания","JP":"Япония","SG":"Сингапур","CA":"Канада","AU":"Австралия",
    "BR":"Бразилия","IN":"Индия","IT":"Италия","ES":"Испания","CH":"Швейцария",
    "AT":"Австрия","BE":"Бельгия","DK":"Дания","FI":"Финляндия","NO":"Норвегия",
    "SE":"Швеция","PL":"Польша","CZ":"Чехия","HU":"Венгрия","RO":"Румыния","BG":"Болгария",
    "GR":"Греция","PT":"Португалия","IE":"Ирландия","TR":"Турция","IL":"Израиль","AE":"ОАЭ",
    "SA":"Саудовская Аравия","ZA":"ЮАР","MX":"Мексика","AR":"Аргентина","CL":"Чили",
    "CO":"Колумбия","MY":"Малайзия","VN":"Вьетнам","TH":"Таиланд","PH":"Филиппины",
    "ID":"Индонезия","PK":"Пакистан","EG":"Египет","NG":"Нигерия","MA":"Марокко",
    "KE":"Кения","NZ":"Новая Зеландия","HK":"Гонконг","KR":"Южная Корея","TW":"Тайвань",
    "EE":"Эстония","LV":"Латвия","LT":"Литва"}


def fetch_configs_from_url(url: str):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return [l.strip() for l in r.text.splitlines()
                if l.strip() and not l.startswith('#')]
    except Exception as e:
        print(f"Error {url}: {e}")
        return []


def is_secure_config(c: str) -> bool:
    cl = c.lower()
    if 'allowinsecure=1' in cl or 'insecure=1' in cl:
        return False
    if 'security=none' in cl or 'tls=none' in cl:
        return False
    return True


def get_config_id(config: str) -> str:
    proto = get_protocol(config)
    h, p = extract_host_port(config)
    if not h or not p:
        return config
    return f"{proto}@{h}:{p}"


def process_config(config: str, tag: str, reader):
    """Verify one config and build its renamed form. Returns result tuple or None."""
    if not is_secure_config(config) or 'anycast' in config.lower():
        return None
    host, port = extract_host_port(config)
    if not host or not port or is_private_host(host):
        return None

    ping, ok, _, _ = verify_config(config, TIMEOUT)
    if not ok or ping is None or ping > PING_MAX:
        return None

    name_part = config.split('#', 1)[1].strip() if '#' in config else ""
    sni_m = re.search(r'sni=([^&#]+)', config)
    sni = sni_m.group(1) if sni_m else ""

    # Country cascade (geo.py): GeoIP -> domain -> name. Domain hosts get
    # a DNS resolve first so GeoIP works on hostnames too, not just raw IPs.
    geo_host = host
    if reader:
        resolved = resolve_host(host)
        if resolved:
            geo_host = resolved
    flag, cc = detect_country(geo_host if geo_host != host else host, name_part, reader)

    if cc in ("ZZ", "??") or flag == WHITE_FLAG:
        return None

    parts = [p for p in (tag, "cloudflare" if "cloudflare" in sni.lower() else "") if p]
    city = detect_city_by_ip(geo_host) if cc == "RU" else ""
    if city:
        parts.append(city)
    parts += [flag, COUNTRY_NAMES.get(cc, cc), "t.me/letovpn_free"]
    new_name = config.split('#', 1)[0] + '#' + ' '.join(parts)
    return (config, new_name, cc, ping, None)


def save_chunked(lst, bn, sz=200):
    if not lst:
        return
    i = 1
    while os.path.exists(f"{bn}{i}.txt"):
        os.remove(f"{bn}{i}.txt"); i += 1
    for i in range(0, len(lst), sz):
        fn = i // sz + 1
        with open(f"{bn}{fn}.txt", "w", encoding="utf-8") as f:
            for c in lst[i:i + sz]:
                f.write(c + "\n")
        print(f"  {bn}{fn}.txt: {len(lst[i:i+sz])}")


def main():
    start = time.time()
    init_xray()
    if not SOURCES:
        print("No sources!"); return
    bot = TelegramBot()
    download_geoip_db()
    reader = init_geoip_reader()

    tagged = []
    for url, tag in SOURCES:
        cfgs = fetch_configs_from_url(url)
        print(f"  {url}: {len(cfgs)} [{tag}]")
        tagged.extend((c, tag) for c in cfgs)

    seen, unique = set(), []
    for c, t in tagged:
        cid = get_config_id(c)
        if cid not in seen and 'anycast' not in c.lower():
            seen.add(cid); unique.append((c, t))
    total = len(unique)
    print(f"Total: {total}")
    msg_id = bot.send_start()

    print("\nPass 1...")
    first, checked = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fs = {ex.submit(process_config, c, t, reader): (c, t) for c, t in unique}
        for f in concurrent.futures.as_completed(fs):
            try:
                r = f.result()
            except Exception as e:
                r = None
                print(f"  worker error: {e}")
            if r:
                first.append(r)
            checked += 1
            if msg_id and checked % 5 == 0:
                bot.update_progress(msg_id, checked, total, len(first), time.time() - start)
            if checked % 50 == 0:
                print(f"  {checked}/{total}. Found: {len(first)}")
    print(f"  Pass 1: {len(first)}")

    if first:
        print("\nPass 2...")
        second, checked2 = [], 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            fs = [ex.submit(process_config, r[0], "", reader) for r in first]
            for f in concurrent.futures.as_completed(fs):
                try:
                    r = f.result()
                except Exception as e:
                    r = None
                    print(f"  worker error: {e}")
                if r:
                    second.append(r)
                checked2 += 1
                if msg_id and checked2 % 5 == 0:
                    bot.update_progress(msg_id, len(first) + checked2, len(first) * 2, len(second), time.time() - start)
        print(f"  Pass 2: {len(second)} confirmed")
        passed = {r[0] for r in second}
        results = [r for r in first if r[0] in passed]
        print(f"  Final: {len(results)}/{len(first)}")
    else:
        second = []
        results = []

    ru = [(r[1], r[3]) for r in results if r[2] == "RU"]
    other = [(r[1], r[2], r[3]) for r in results if r[2] not in ("RU", "??")]
    other.sort(key=lambda x: (COUNTRY_SORT_ORDER.get(x[1], 50), x[2]))
    ru.sort(key=lambda x: x[1])
    fast = len([r for r in results if r[3] < PING_GOOD_THRESHOLD])
    bot.send_final(total, len(results), fast, time.time() - start, len(first), len(second))

    os.makedirs("protocols", exist_ok=True)
    pf = {"VLESS": [], "VMESS": [], "TROJAN": [], "SS": []}
    for r in results:
        if r[2] == "??":
            continue
        nc = r[1]
        proto = get_protocol(nc)
        if proto in pf:
            pf[proto].append(nc)

    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M:%S")
    repo = os.getenv("GITHUB_REPOSITORY", "adop1344-bot/LetoVPN_free")
    h = (f"#announce: Updated: {now}\n"
         f"#support-url: https://t.me/@why_im_gay\n"
         f"#profile-update-interval: 1\n\n")

    with open("configs.txt", "w", encoding="utf-8") as f:
        f.write(f"{h}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/configs.txt\n"
                f"#profile-title: TG@LetoVPN_Free\n\n")
        for cfg, _, _ in other:
            f.write(cfg + "\n")
    print(f"  configs.txt: {len(other)}")
    save_chunked([c for c, _, _ in other], "configs", 200)

    with open("ru.txt", "w", encoding="utf-8") as f:
        f.write(f"{h}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/ru.txt\n"
                f"#profile-title: ru TG@LetoVPN_Free\n\n")
        for c, _ in ru:
            f.write(c + "\n")
    print(f"  ru.txt: {len(ru)}")

    with open("configs_hiddify.txt", "w", encoding="utf-8") as f:
        for c, _, _ in other:
            f.write(c + "\n")
    with open("ru_hiddify.txt", "w", encoding="utf-8") as f:
        for c, _ in ru:
            f.write(c + "\n")

    for proto, cs in pf.items():
        if cs:
            with open(f"protocols/{proto}.txt", "w", encoding="utf-8") as f:
                f.write(f"{h}#profile-web-page-url: https://raw.githubusercontent.com/{repo}/main/protocols/{proto}.txt\n"
                        f"#profile-title: {proto} TG@LetoVPN_Free\n\n")
                for c in cs:
                    f.write(c + "\n")

    print(f"\nDone! {time.time() - start:.1f}s")
    if reader:
        reader.close()


if __name__ == "__main__":
    main()
