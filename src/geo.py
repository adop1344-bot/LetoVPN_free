#!/usr/bin/env python3
"""
Geo / country-detection helpers — single source of truth for all
flag/country/city logic. app.py uses these; do not duplicate inline.

Detection cascade for a config:
    1. GeoLite2 MMDB (reader.country(host)) — IP hosts, most reliable
    2. DOMAIN_MAP suffix match (domains.txt, longest suffix wins)
    3. Name-based heuristics (flag emoji / keyword / ISO code in #name)
    4. give up -> ("🏳️", "ZZ")
"""
import ipaddress
import re
import socket
from typing import Optional, Tuple

from src.config import (
    GEOIP_FILE,
    GEOIP_URL,
    load_cities,
    load_domains,
    load_flags,
    load_keywords,
)

WHITE_FLAG = "\U0001F9F3"

COUNTRY_FLAGS = load_flags()
KEYWORDS = load_keywords()
CITIES = load_cities()
DOMAIN_MAP = load_domains()

# Pre-sorted longest-suffix-first so .co.uk wins over .uk
_DOMAIN_SUFFIXES = sorted(DOMAIN_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_private_host(host: str) -> bool:
    """Reject loopback/private/reserved hosts — they can never be real VPN exits."""
    try:
        return ipaddress.ip_address(host).is_global is False
    except ValueError:
        hl = (host or "").lower()
        return hl in ("localhost",) or hl.endswith(".local") or hl.endswith(".internal")


def resolve_host(host: str, timeout: float = 2.0) -> Optional[str]:
    """DNS-resolve a hostname so GeoIP can work on domain configs too."""
    if not host or is_ip(host):
        return host
    try:
        socket.setdefaulttimeout(timeout)
        return socket.gethostbyname(host)
    except Exception:
        return None


def download_geoip_db() -> bool:
    """Fetch GeoLite2-Country.mmdb (gzipped) if missing. Returns True if file exists after call."""
    import gzip
    import os
    import shutil
    import requests

    if os.path.exists(GEOIP_FILE):
        return True
    try:
        r = requests.get(GEOIP_URL, timeout=30)
        r.raise_for_status()
        gz = GEOIP_FILE + ".gz"
        with open(gz, "wb") as f:
            f.write(r.content)
        with gzip.open(gz, "rb") as fi, open(GEOIP_FILE, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        os.remove(gz)
        return True
    except Exception as e:
        print(f"GeoIP download failed: {e}")
        return False


def init_geoip_reader():
    """Open the MMDB reader if the DB file is present; returns None otherwise."""
    import os
    try:
        import geoip2.database
        if os.path.exists(GEOIP_FILE):
            return geoip2.database.Reader(GEOIP_FILE)
    except Exception as e:
        print(f"GeoIP reader init failed: {e}")
    return None


def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    """Look up host (IP or already-resolved) in GeoLite2. -> (flag, ISO code | 'ZZ')."""
    try:
        if reader:
            r = reader.country(host)
            if r and r.country and r.country.iso_code:
                code = r.country.iso_code
                return COUNTRY_FLAGS.get(code, WHITE_FLAG), code
    except Exception:
        pass
    return WHITE_FLAG, "ZZ"


def detect_country_by_domain(host: str) -> Tuple[str, str]:
    """Match host against DOMAIN_MAP TLD/suffix list (longest suffix wins)."""
    if not host:
        return WHITE_FLAG, "ZZ"
    hl = host.lower()
    for domain, code in _DOMAIN_SUFFIXES:
        if hl.endswith(domain):
            return COUNTRY_FLAGS.get(code, WHITE_FLAG), code
    return WHITE_FLAG, "ZZ"


def detect_country_from_name(name: str) -> Tuple[str, str]:
    """Heuristics on the config's #name: flag emoji, keyword, bare ISO code."""
    nl = name.lower()
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name:
            return flag, code
    for code, words in KEYWORDS.items():
        for w in words:
            if w in nl:
                return COUNTRY_FLAGS.get(code, WHITE_FLAG), code
    m = re.search(r'\b([A-Z]{2})\b', name)
    if m and m.group(1) in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[m.group(1)], m.group(1)
    return WHITE_FLAG, "ZZ"


def detect_country(host: str, name: str, reader) -> Tuple[str, str]:
    """Full cascade: GeoIP -> domain suffix -> name heuristics.
    Returns (flag, country_code). 'ZZ' = unknown, '??' = suspicious .ru host."""
    flag, cc = get_country_geoip(host, reader)

    if cc == "ZZ" and not is_ip(host or ""):
        flag, cc = detect_country_by_domain(host)

    # .ru host that GeoIP swears is NOT Russia -> probably a spoofed/redirected
    # entry; mark '??' so the caller can drop or quarantine it
    if host and host.lower().endswith((".ru", ".рф", ".su")) and cc != "RU":
        return WHITE_FLAG, "??"

    if cc == "ZZ" and name:
        flag, cc = detect_country_from_name(name)

    return flag, cc


def detect_city_by_ip(host: str) -> str:
    """Rough Russian-city guess from first two IPv4 octets (cities.txt)."""
    if not host or not is_ip(host):
        return ""
    if ":" in host:  # IPv6 — cities.txt is v4-only
        return ""
    parts = host.split(".")
    mask = f"{parts[0]}.{parts[1]}"
    return CITIES.get(mask, "")


def get_domain_note(host: str) -> str:
    """Human-friendly ' [domain.tld]' suffix for .ru/.рф/.su hosts."""
    if not host:
        return ""
    hl = host.lower()
    if hl.endswith((".ru", ".рф", ".su")):
        parts = hl.split(".")
        if len(parts) >= 2:
            return f" [{parts[-2]}.{parts[-1]}]"
    return ""
