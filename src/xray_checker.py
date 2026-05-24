#!/usr/bin/env python3
import os
import subprocess
import time
import json
import tempfile
import urllib.request
import zipfile
from typing import Optional

XRAY_AVAILABLE = False

def download_xray():
    """Скачивает Xray бинарник, если его нет"""
    if os.path.exists("xray"):
        return True
    
    print("📥 Скачиваю Xray...")
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        urllib.request.urlretrieve(url, "xray.zip")
        
        with zipfile.ZipFile("xray.zip", "r") as zip_ref:
            zip_ref.extract("xray", ".")
        
        os.chmod("xray", 0o755)
        os.remove("xray.zip")
        print("✅ Xray установлен")
        return True
    except Exception as e:
        print(f"❌ Ошибка скачивания Xray: {e}")
        return False

def xray_ping(config: str, timeout: int = 5) -> Optional[float]:
    """
    Проверяет конфиг через Xray
    Возвращает пинг в мс или None
    """
    config_path = None
    try:
        # Создаём временный конфиг для Xray
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_path = f.name
            # Преобразуем строку конфига в формат Xray
            xray_config = convert_to_xray_config(config)
            if not xray_config:
                return None
            json.dump(xray_config, f)
        
        # Запускаем Xray в режиме проверки
        start = time.time()
        result = subprocess.run(
            ["xray", "test", "-config", config_path],
            capture_output=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            return (time.time() - start) * 1000
        
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"Xray error: {e}")
        return None
    finally:
        if config_path and os.path.exists(config_path):
            os.unlink(config_path)

def convert_to_xray_config(config_line: str) -> dict:
    """Преобразует VLESS/VMESS строку в формат Xray"""
    import urllib.parse
    import re
    
    if config_line.startswith('vless://'):
        # Парсим VLESS
        match = re.search(r'vless://([^@]+)@([^:]+):(\d+)(.*)', config_line)
        if not match:
            return None
        
        uuid = match.group(1)
        host = match.group(2)
        port = int(match.group(3))
        params = match.group(4)
        
        # Парсим параметры
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
    
    elif config_line.startswith('vmess://'):
        # TODO: добавить парсинг vmess
        return None
    
    return None
