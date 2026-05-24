#!/usr/bin/env python3
import re
from typing import Tuple

from src.config import COUNTRY_FLAGS, KEYWORDS, CITIES, DOMAIN_MAP

def detect_country_by_domain(host: str) -> Tuple[str, str]:
    if not host:
        return "🏳️", "ZZ"
    host_lower = host.lower()
    for domain, code in sorted(DOMAIN_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if host_lower.endswith(domain):
            return COUNTRY_FLAGS.get(code, "🏳️"), code
    return "🏳️", "ZZ"

def detect_country_from_name(name: str) -> Tuple[str, str]:
    name_lower = name.lower()
    for code, flag in COUNTRY_FLAGS.items():
        if flag in name:
            return flag, code
    for code, words in KEYWORDS.items():
        for word in words:
            if word in name_lower:
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    match = re.search(r'\b([A-Z]{2})\b', name)
    if match and match.group(1) in COUNTRY_FLAGS:
        return COUNTRY_FLAGS[match.group(1)], match.group(1)
    return "🏳️", "ZZ"

def get_country_geoip(host: str, reader) -> Tuple[str, str]:
    try:
        if reader:
            response = reader.country(host)
            if response and response.country and response.country.iso_code:
                code = response.country.iso_code
                return COUNTRY_FLAGS.get(code, "🏳️"), code
    except:
        pass
    return "🏳️", "ZZ"

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
    if host_lower.endswith('.ru') or host_lower.endswith('.рф') or host_lower.endswith('.su'):
        parts = host_lower.split('.')
        if len(parts) >= 2:
            return f" [{parts[-2]}.{parts[-1]}]"
    return ""
