#!/usr/bin/env python3
import socket
import time
import re
import base64
import json
import random
from typing import Tuple, Optional

XRAY_AVAILABLE = False
USE_TCP_FALLBACK = True  # TCP как запасной

def init_xray():
    global XRAY_AVAILABLE
    try:
        from src.xray_checker import download_xray, xray_ping
        if download_xray():
            XRAY_AVAILABLE = True
            print("✅ Xray готов к использованию (основной метод проверки)")
        else:
            print("⚠️ Xray не установлен, использую только TCP ping")
    except Exception as e:
        print(f"⚠️ Ошибка инициализации Xray: {e}")
    return XRAY_AVAILABLE

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    """Быстрый TCP ping"""
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def vless_handshake(host: str, port: int, timeout: float) -> Optional[float]:
    """Проверяет VLESS через рукопожатие (быстро, но менее точно)"""
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        # Отправляем VLESS приветствие (16 случайных байт)
        sock.send(bytes([random.randint(0, 255) for _ in range(16)]))
        response = sock.recv(16)
        sock.close()
        if len(response) == 16:
            return (time.time() - start) * 1000
        return None
    except:
        return None

def verify_config(config: str, host: str, port: int, timeout: float) -> Tuple[Optional[float], bool, bool]:
    """
    Двухступенчатая проверка:
    1. TCP ping (быстрый отсев)
    2. Xray (точная проверка, если доступен)
    Возвращает: (пинг, успех, использован_Xray)
    """
    # --- ШАГ 1: TCP ping (быстрый отсев) ---
    ping = tcp_ping(host, port, timeout)
    if ping is None:
        return (None, False, False)
    
    # --- ШАГ 2: Xray проверка (если доступен) ---
    if XRAY_AVAILABLE:
        try:
            from src.xray_checker import xray_ping
            xray_ping_result = xray_ping(config, int(timeout))
            if xray_ping_result is not None:
                # Xray успешен — используем его результат
                return (xray_ping_result, True, True)
            else:
                # Xray не прошёл — конфиг мёртв (даже если TCP прошёл)
                return (None, False, False)
        except Exception as e:
            print(f"Xray ошибка: {e}")
            # Если Xray упал — используем TCP как fallback
            return (ping, True, False)
    
    # Если Xray недоступен — используем TCP ping
    return (ping, True, False)

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
