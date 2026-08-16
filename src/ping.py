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

def xray_check(config: str, host: str, port: int, timeout: int) -> Optional[float]:
    """Проверяет конфиг через Xray (запасной метод)"""
    if not XRAY_AVAILABLE:
        return None
    
    try:
        import tempfile
        import json as json_lib
        
        xray_config = convert_to_xray_config(config)
        if not xray_config:
            return None
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json_lib.dump(xray_config, f)
            config_path = f.name
        
        start = time.time()
        result = subprocess.run(
            ["xray", "run", "-config", config_path],
            capture_output=True,
            timeout=timeout
        )
        
        os.unlink(config_path)
        
        # Если xray запустился без ошибок - конфиг рабочий
        if result.returncode == 0 or "Xray" in result.stderr.decode():
            return (time.time() - start) * 1000
        return None
    except subprocess.TimeoutExpired:
        # Таймаут = xray запустился и работал = конфиг валидный
        try:
            os.unlink(config_path)
        except:
            pass
        return timeout * 1000  # возвращаем пинг = timeout (примерно)
    except Exception as e:
        return None

def convert_to_xray_config(config_line: str) -> Optional[dict]:
    """Преобразует VLESS/VMESS/TROJAN строку в формат Xray"""
    import urllib.parse
    
    if config_line.startswith('vless://'):
        match = re.search(r'vless://([^@]+)@([^:]+):(\d+)(.*)', config_line)
        if not match:
            return None
        
        uuid = match.group(1)
        host = match.group(2)
        port = int(match.group(3))
        params = match.group(4)
        
        parsed = urllib.parse.urlparse("?" + params.lstrip("?#&"))
        query = urllib.parse.parse_qs(parsed.query)
        
        stream_settings = {
            "network": query.get("type", ["tcp"])[0],
            "security": query.get("security", ["none"])[0],
        }
        
        # TLS/Reality настройки
        security = query.get("security", ["none"])[0]
        if security in ["tls", "reality"]:
            stream_settings["tlsSettings"] = {
                "serverName": query.get("sni", [host])[0],
                "fingerprint": query.get("fp", ["chrome"])[0] if query.get("fp") else "chrome",
            }
            if security == "reality":
                stream_settings["tlsSettings"]["show"] = False
                stream_settings["tlsSettings"]["publicKey"] = query.get("pbk", [""])[0]
                stream_settings["tlsSettings"]["shortId"] = query.get("sid", [""])[0]
                stream_settings["tlsSettings"]["spiderX"] = query.get("spx", ["/"])[0]
        
        return {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "port": 1080,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True}
            }],
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
                "streamSettings": stream_settings
            }]
        }
    
    elif config_line.startswith('vmess://'):
        try:
            b64 = config_line[8:] + '=' * (4 - len(config_line[8:]) % 4)
            data = json.loads(base64.b64decode(b64))
            
            stream_settings = {
                "network": data.get("net", "tcp"),
                "security": data.get("tls", "none"),
            }
            
            if data.get("tls") == "tls":
                stream_settings["tlsSettings"] = {
                    "serverName": data.get("sni", data.get("host", data.get("add", ""))),
                    "fingerprint": data.get("fp", "chrome"),
                }
            
            return {
                "log": {"loglevel": "none"},
                "inbounds": [{
                    "port": 1080,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"udp": True}
                }],
                "outbounds": [{
                    "protocol": "vmess",
                    "settings": {
                        "vnext": [{
                            "address": data.get("add", ""),
                            "port": int(data.get("port", 0)),
                            "users": [{
                                "id": data.get("id", ""),
                                "alterId": int(data.get("aid", 0)),
                                "security": data.get("scy", "auto"),
                            }]
                        }]
                    },
                    "streamSettings": stream_settings
                }]
            }
        except:
            return None
    
    elif config_line.startswith('trojan://'):
        match = re.search(r'trojan://([^@]+)@([^:]+):(\d+)(.*)', config_line)
        if not match:
            return None
        
        password = match.group(1)
        host = match.group(2)
        port = int(match.group(3))
        params = match.group(4) if match.group(4) else ""
        
        parsed = urllib.parse.urlparse("?" + params.lstrip("?#&"))
        query = urllib.parse.parse_qs(parsed.query)
        
        stream_settings = {
            "network": query.get("type", ["tcp"])[0],
            "security": "tls",
            "tlsSettings": {
                "serverName": query.get("sni", [host])[0],
                "fingerprint": query.get("fp", ["chrome"])[0] if query.get("fp") else "chrome",
            }
        }
        
        return {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "port": 1080,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True}
            }],
            "outbounds": [{
                "protocol": "trojan",
                "settings": {
                    "servers": [{
                        "address": host,
                        "port": port,
                        "password": password,
                    }]
                },
                "streamSettings": stream_settings
            }]
        }
    
    return None

def verify_config(config: str, host: str, port: int, timeout: float) -> Tuple[Optional[float], bool, bool, Optional[float]]:
    """
    Проверка конфига:
    1. TCP ping (быстрый отсев)
    2. Xray (если доступен, проверяет реальную работу протокола)
    Возвращает: (пинг, успех, использован_Xray, скорость_Мбит/с)
    """
    # ШАГ 1: TCP ping — быстрый отсев мёртвых серверов
    ping = tcp_ping(host, port, timeout)
    if ping is None:
        return (None, False, False, None)
    
    # ШАГ 2: Xray — если доступен, пробуем проверить реальный протокол
    if XRAY_AVAILABLE:
        xray_ping = xray_check(config, host, port, int(timeout))
        if xray_ping is not None:
            return (xray_ping, True, True, None)
        # Если Xray не сработал — не страшно, используем TCP ping
    
    # ШАГ 3: Fallback — TCP ping (сервер жив, порт открыт)
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