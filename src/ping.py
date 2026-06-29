#!/usr/bin/env python3
import socket
import time
import re
import base64
import json
import random
import shutil
import subprocess
import os
from typing import Tuple, Optional

XRAY_AVAILABLE = False
USE_TCP_FALLBACK = True

def init_xray():
    """Проверяет, доступен ли Xray в системе (запасной метод)"""
    global XRAY_AVAILABLE
    
    xray_path = shutil.which("xray")
    if xray_path:
        try:
            result = subprocess.run(["xray", "version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                XRAY_AVAILABLE = True
                print(f"✅ Xray доступен как запасной метод ({xray_path})")
                return True
        except Exception as e:
            print(f"⚠️ Xray найден, но не работает: {e}")
    
    print("⚠️ Xray не найден, использую TCP ping")
    return False

def tcp_ping(host: str, port: int, timeout: float) -> Optional[float]:
    """Быстрый TCP ping"""
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except:
        return None

def speed_test(host: str, port: int, timeout: float) -> Tuple[Optional[float], Optional[float]]:
    """
    Проверяет скорость конфига через загрузку небольшого файла
    Возвращает (пинг, скорость_Мбит/с) или (None, None)
    """
    try:
        import urllib.request
        proxies = {
            "http": f"socks5://{host}:{port}",
            "https": f"socks5://{host}:{port}"
        }
        
        # Создаём открывашку с прокси
        proxy_handler = urllib.request.ProxyHandler(proxies)
        opener = urllib.request.build_opener(proxy_handler)
        
        # Загружаем небольшой файл для теста скорости (~1 МБ)
        test_url = "https://speed.cloudflare.com/__down?bytes=1000000"
        start = time.time()
        
        response = opener.open(test_url, timeout=timeout)
        data = response.read()
        elapsed = time.time() - start
        
        if len(data) > 0:
            # Скорость в Мбит/с
            speed_mbps = (len(data) * 8) / (elapsed * 1000000)
            ping_ms = elapsed * 1000
            return (ping_ms, speed_mbps)
        return (None, None)
    except:
        return (None, None)

def speed_test_simple(host: str, port: int, timeout: float) -> Tuple[Optional[float], Optional[float]]:
    """
    Простая проверка скорости через HTTP HEAD запрос
    Быстрее, но менее точная
    """
    try:
        import urllib.request
        proxies = {
            "http": f"socks5://{host}:{port}",
            "https": f"socks5://{host}:{port}"
        }
        
        proxy_handler = urllib.request.ProxyHandler(proxies)
        opener = urllib.request.build_opener(proxy_handler)
        
        start = time.time()
        response = opener.open("https://www.google.com/generate_204", timeout=timeout)
        elapsed = time.time() - start
        
        if response.getcode() in [200, 204]:
            ping_ms = elapsed * 1000
            # Примерная оценка скорости (не точная)
            speed_mbps = 100 / (ping_ms + 1)  # условная оценка
            return (ping_ms, speed_mbps)
        return (None, None)
    except:
        return (None, None)

def xray_check(config: str, host: str, port: int, timeout: int) -> Optional[float]:
    """Проверяет конфиг через Xray (запасной метод)"""
    if not XRAY_AVAILABLE:
        return None
    
    try:
        import tempfile
        import json as json_lib
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            xray_config = convert_to_xray_config(config)
            if not xray_config:
                return None
            json_lib.dump(xray_config, f)
            config_path = f.name
        
        start = time.time()
        result = subprocess.run(
            ["xray", "test", "-config", config_path],
            capture_output=True,
            timeout=timeout
        )
        
        os.unlink(config_path)
        
        if result.returncode == 0:
            return (time.time() - start) * 1000
        return None
    except Exception as e:
        return None

def convert_to_xray_config(config_line: str) -> dict:
    """Преобразует VLESS/VMESS строку в формат Xray"""
    import urllib.parse
    
    if config_line.startswith('vless://'):
        match = re.search(r'vless://([^@]+)@([^:]+):(\d+)(.*)', config_line)
        if not match:
            return None
        
        uuid = match.group(1)
        host = match.group(2)
        port = int(match.group(3))
        params = match.group(4)
        
        parsed = urllib.parse.urlparse(params)
        query = urllib.parse.parse_qs(parsed.query)
        
        return {
            "outbounds": [{
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": port,
                        "users": [{
                            "id": uuid,
                            "encryption": query.get("encryption", ["none"])[0],
                            "flow": query.get("flow", [""])[0]
                        }]
                    }]
                },
                "streamSettings": {
                    "network": query.get("type", ["tcp"])[0],
                    "security": query.get("security", ["none"])[0],
                    "tlsSettings": {
                        "serverName": query.get("sni", [""])[0],
                        "fingerprint": query.get("fp", ["chrome"])[0]
                    } if query.get("security", ["none"])[0] in ["tls", "reality"] else None
                }
            }]
        }
    return None

def verify_config(config: str, host: str, port: int, timeout: float) -> Tuple[Optional[float], bool, bool, Optional[float]]:
    """
    Четырёхступенчатая проверка:
    1. TCP ping (быстрый отсев)
    2. Скорость (если TCP прошёл)
    3. Xray (запасной метод, если скорость не удалась)
    Возвращает: (пинг, успех, использован_Xray, скорость_Мбит/с)
    """
    # ШАГ 1: TCP ping
    ping = tcp_ping(host, port, timeout)
    if ping is None:
        return (None, False, False, None)
    
    # ШАГ 2: Проверка скорости
    speed_ping, speed_mbps = speed_test_simple(host, port, timeout)
    
    # ШАГ 3: Xray (запасной, если скорость не удалась)
    if speed_ping is None and XRAY_AVAILABLE:
        xray_ping = xray_check(config, host, port, int(timeout))
        if xray_ping is not None:
            return (xray_ping, True, True, None)
        else:
            return (None, False, False, None)
    
    # Если скорость удалась — используем её результат
    if speed_ping is not None:
        return (speed_ping, True, False, speed_mbps)
    
    # Fallback: только TCP
    return (ping, True, False, None)

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
