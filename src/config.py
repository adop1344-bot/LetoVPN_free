#!/usr/bin/env python3
import os, json, re
from typing import List, Dict, Tuple

SOURCES_FILE = "sources.txt"
FLAGS_FILE = "flags.txt"
KEYWORDS_FILE = "keywords.txt"
CITIES_FILE = "cities.txt"
DOMAINS_FILE = "domains.txt"

TIMEOUT = 5.0
MAX_WORKERS = 5
PING_GOOD_THRESHOLD = 500
PING_MAX = 100000

GEOIP_URL = "https://cdn.jsdelivr.net/npm/geolite2-country/GeoLite2-Country.mmdb.gz"
GEOIP_FILE = "GeoLite2-Country.mmdb"

def load_sources() -> List[Tuple[str, str]]:
    r = []
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith('#'): continue
                if ' #' in l:
                    url, tag = l.split(' #', 1)
                    r.append((url.strip(), tag.strip()))
                else: r.append((l, ""))
    except: pass
    return r

def load_flags() -> Dict[str, str]:
    r = {}
    try:
        with open(FLAGS_FILE, "r", encoding="utf-8") as f:
            for l in f:
                if ':' in l: k, v = l.strip().split(':', 1); r[k] = v
    except: pass
    return r

def load_keywords() -> Dict[str, List[str]]:
    r = {}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for l in f:
                if ':' in l: k, v = l.strip().split(':', 1); r[k] = [w.strip().lower() for w in v.split(',')]
    except: pass
    return r

def load_cities() -> Dict[str, str]:
    r = {}
    try:
        with open(CITIES_FILE, "r", encoding="utf-8") as f:
            for l in f:
                if ':' in l: k, v = l.strip().split(':', 1); r[k] = v
    except: pass
    return r

def load_domains() -> Dict[str, str]:
    r = {}
    try:
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            for l in f:
                l = l.strip()
                if l and not l.startswith('#') and ':' in l:
                    d, c = l.split(':', 1); r[d.lower()] = c
    except: pass
    return r
