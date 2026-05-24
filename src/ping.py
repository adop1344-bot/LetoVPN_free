#!/usr/bin/env python3
import socket
import time
import re
import base64
import json
from typing import Tuple, Optional

XRAY_AVAILABLE = False

def init_xray():
    global XRAY_AVAILABLE
    try:
        from src.xray_checker import download_xray, xray_ping
        if download_xray():
            XRAY_AVAILABLE = True
            print("✅ Xray готов к использованию")
        else:
            print("⚠️ Xray не установлен, использую TCP ping")
    except Exception as e:
        print(f"⚠️ Ошибка инициализации Xray: {e}")
    return XRAY_AVAILABLE

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def verify_config(config: str, host: str, port: int, timeout: float) -> Tuple[Optional[float], bool]:
    """Проверка конфига: сначала Xray, потом TCP ping как fallback"""
    
    # Пробуем Xray проверку (если доступна)
    if XRAY_AVAILABLE:
        try:
            from src.xray_checker import xray_ping
            ping = xray_ping(config, int(timeout))
            if ping is not None:
                return (ping, True)
        except Exception as e:
            print(f"Xray проверка не удалась: {e}")
    
    # Fallback: TCP ping
    ping = tcp_ping(host, port, timeout)
    return (ping, ping is not None)

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
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
