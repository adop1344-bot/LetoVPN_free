#!/usr/bin/env python3
import os
import json
import re
from typing import List, Dict

SOURCES_FILE = "sources.txt"
FLAGS_FILE = "flags.txt"
KEYWORDS_FILE = "keywords.txt"
CITIES_FILE = "cities.txt"
DOMAINS_FILE = "domains.txt"

TIMEOUT = 5.0
MAX_WORKERS = 150
PING_GOOD_THRESHOLD = 300
PING_MAX = 100000

GEOIP_URL = "https://cdn.jsdelivr.net/npm/geolite2-country/GeoLite2-Country.mmdb.gz"
GEOIP_FILE = "GeoLite2-Country.mmdb"

def load_sources() -> List[str]:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except:
        return []

def load_flags() -> Dict[str, str]:
    code_to_flag = {}
    try:
        with open(FLAGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, flag = line.strip().split(':', 1)
                    code_to_flag[code] = flag
    except:
        pass
    return code_to_flag

def load_keywords() -> Dict[str, List[str]]:
    keywords = {}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    code, words_str = line.strip().split(':', 1)
                    keywords[code] = [w.strip().lower() for w in words_str.split(',')]
    except:
        pass
    return keywords

def load_cities() -> Dict[str, str]:
    cities = {}
    try:
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    mask, city = line.strip().split(':', 1)
                    cities[mask] = city
    except:
        pass
    return cities

def load_domains() -> Dict[str, str]:
    domain_to_country = {}
    try:
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if ':' in line:
                        domain, code = line.split(':', 1)
                        domain_to_country[domain.lower()] = code
    except:
        pass
    return domain_to_country
