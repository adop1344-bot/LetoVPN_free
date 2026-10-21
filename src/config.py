#!/usr/bin/env python3
import os
import re
from typing import Dict, List, Tuple

SOURCES_FILE = "sources.txt"
FLAGS_FILE = "flags.txt"
KEYWORDS_FILE = "keywords.txt"
CITIES_FILE = "cities.txt"
DOMAINS_FILE = "domains.txt"

TIMEOUT = 4.0
MAX_WORKERS = 20
PING_GOOD_THRESHOLD = 500
PING_MAX = 100000

GEOIP_URL = "https://cdn.jsdelivr.net/npm/geolite2-country/GeoLite2-Country.mmdb.gz"
GEOIP_FILE = "GeoLite2-Country.mmdb"

# Generic TLDs that must NOT be treated as US evidence
GENERIC_TLDS = {".com", ".org", ".net", ".io", ".co", ".xyz", ".me", ".tv", ".cc", ".biz"}


def _load_kv(path: str, lowercase_keys: bool = False) -> Dict[str, str]:
    r = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith('#') or ':' not in l:
                    continue
                k, v = l.split(':', 1)
                r[k.lower() if lowercase_keys else k] = v
    except FileNotFoundError:
        pass
    return r


def load_sources() -> List[Tuple[str, str]]:
    r = []
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith('#'):
                    continue
                if ' #' in l:
                    url, tag = l.split(' #', 1)
                    r.append((url.strip(), tag.strip()))
                else:
                    r.append((l, ""))
    except FileNotFoundError:
        pass
    return r


def load_flags() -> Dict[str, str]:
    return _load_kv(FLAGS_FILE)


def load_cities() -> Dict[str, str]:
    return _load_kv(CITIES_FILE)


def load_keywords() -> Dict[str, List[str]]:
    r = {}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith('#') or ':' not in l:
                    continue
                k, v = l.split(':', 1)
                r[k] = [w.strip().lower() for w in v.split(',') if w.strip()]
    except FileNotFoundError:
        pass
    return r


def load_domains() -> Dict[str, str]:
    """
    domains.txt maps suffix -> ISO country. Generic TLDs (.com/.org/...)
    are intentionally skipped: `host.com` tells you nothing about location
    and previously mis-labeled everything as US.
    """
    raw = _load_kv(DOMAINS_FILE, lowercase_keys=True)
    return {d: c for d, c in raw.items() if d not in GENERIC_TLDS}
