#!/usr/bin/env python3
import socket
import time
import re
import base64
import json
from typing import Tuple, Optional

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    """Простой TCP ping"""
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def verify_config(config: str, host: str, port: int, timeout: float) -> Tuple[Optional[float], bool]:
    """Проверка конфига (только TCP)"""
    ping = tcp_ping(host, port, timeout)
    return (ping, ping is not None)

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    """Извлекает хост и порт из конфига"""
    if config.startswith('vless://'):
        match = re.search(r'vless://[^@]+@([^:?#]+):(\d+)', config)
        if match:
            return match.group(1), int(match.group(2))
    elif config.startswith('vmess://'):
        try:
            b64 = config[8:] + '=' * (4 - len(config[8:]) % 4)
            data = json.loads(base64.b64decode(b64))
            return data.get('add'), int(data.get('port', 0))
        except:
            pass
    elif config.startswith('trojan://'):
        match = re.search(r'trojan://[^@]+@([^:?#]+):(\d+)', config)
        if match:
            return match.group(1), int(match.group(2))
    return None, None

def get_protocol(config: str) -> str:
    if config.startswith('vless://'): return "VLESS"
    elif config.startswith('vmess://'): return "VMESS"
    elif config.startswith('trojan://'): return "TROJAN"
    return ""
