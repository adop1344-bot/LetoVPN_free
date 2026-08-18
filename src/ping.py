#!/usr/bin/env python3
import socket
import time
import re
import base64
import json
import shutil
import subprocess
import os
import urllib.request
from typing import Tuple, Optional

XRAY_AVAILABLE = False
REAL_PING_URL = "https://www.gstatic.com/generate_204"

def init_xray():
    global XRAY_AVAILABLE
    xray_path = shutil.which("xray")
    if xray_path:
        try:
            result = subprocess.run(["xray", "version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                XRAY_AVAILABLE = True
                print(f"Xray available ({xray_path})")
                return True
        except:
            pass
    print("Xray not found, VPN check disabled")
    return False

def xray_check(config: str, timeout: int) -> Optional[float]:
    if not XRAY_AVAILABLE:
        return None
    config_path = None
    try:
        import tempfile, json as json_lib
        xray_config = convert_to_xray_config(config)
        if not xray_config:
            return None
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json_lib.dump(xray_config, f)
            config_path = f.name
        start = time.time()
        process = subprocess.Popen(["xray", "run", "-config", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": "socks5://127.0.0.1:1080", "https": "socks5://127.0.0.1:1080"})
            opener = urllib.request.build_opener(proxy_handler)
            response = opener.open(REAL_PING_URL, timeout=timeout)
            if response.getcode() in [200, 204, 301, 302]:
                elapsed = (time.time() - start) * 1000
                process.kill(); process.wait()
                try: os.unlink(config_path)
                except: pass
                return elapsed
        except:
            pass
        process.kill(); process.wait()
        try: os.unlink(config_path)
        except: pass
        return None
    except:
        if config_path:
            try: os.unlink(config_path)
            except: pass
        return None

def convert_to_xray_config(line: str) -> Optional[dict]:
    import urllib.parse
    if line.startswith('vless://'):
        m = re.search(r'vless://([^@]+)@([^:]+):(\d+)(.*)', line)
        if not m: return None
        u, h, p, qs = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        q = urllib.parse.parse_qs(urllib.parse.urlparse("?" + qs.lstrip("?#&")).query)
        ss = {"network": q.get("type", ["tcp"])[0], "security": q.get("security", ["none"])[0]}
        sec = q.get("security", ["none"])[0]
        if sec in ["tls", "reality"]:
            ss["tlsSettings"] = {"serverName": q.get("sni", [h])[0], "fingerprint": q.get("fp", ["chrome"])[0] if q.get("fp") else "chrome"}
            if sec == "reality":
                ss["tlsSettings"]["show"] = False
                ss["tlsSettings"]["publicKey"] = q.get("pbk", [""])[0]
                ss["tlsSettings"]["shortId"] = q.get("sid", [""])[0]
                ss["tlsSettings"]["spiderX"] = q.get("spx", ["/"])[0]
        return {"log": {"loglevel": "none"}, "inbounds": [{"port": 1080, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}], "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": h, "port": p, "users": [{"id": u, "encryption": q.get("encryption", ["none"])[0], "flow": q.get("flow", [""])[0]}]}]}, "streamSettings": ss}]}
    elif line.startswith('vmess://'):
        try:
            d = json.loads(base64.b64decode(line[8:] + '=' * (4 - len(line[8:]) % 4)))
            ss = {"network": d.get("net", "tcp"), "security": d.get("tls", "none")}
            if d.get("tls") == "tls":
                ss["tlsSettings"] = {"serverName": d.get("sni", d.get("host", d.get("add", ""))), "fingerprint": d.get("fp", "chrome")}
            return {"log": {"loglevel": "none"}, "inbounds": [{"port": 1080, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}], "outbounds": [{"protocol": "vmess", "settings": {"vnext": [{"address": d.get("add", ""), "port": int(d.get("port", 0)), "users": [{"id": d.get("id", ""), "alterId": int(d.get("aid", 0)), "security": d.get("scy", "auto")}]}]}, "streamSettings": ss}]}
        except: return None
    elif line.startswith('trojan://'):
        m = re.search(r'trojan://([^@]+)@([^:]+):(\d+)(.*)', line)
        if not m: return None
        pw, h, p, qs = m.group(1), m.group(2), int(m.group(3)), m.group(4) or ""
        q = urllib.parse.parse_qs(urllib.parse.urlparse("?" + qs.lstrip("?#&")).query)
        ss = {"network": q.get("type", ["tcp"])[0], "security": "tls", "tlsSettings": {"serverName": q.get("sni", [h])[0], "fingerprint": q.get("fp", ["chrome"])[0] if q.get("fp") else "chrome"}}
        return {"log": {"loglevel": "none"}, "inbounds": [{"port": 1080, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}], "outbounds": [{"protocol": "trojan", "settings": {"servers": [{"address": h, "port": p, "password": pw}]}, "streamSettings": ss}]}
    return None

def verify_config(config: str, timeout: float) -> Tuple[Optional[float], bool, bool, Optional[float]]:
    if not XRAY_AVAILABLE:
        return (None, False, False, None)
    xray_ping = xray_check(config, int(timeout))
    if xray_ping is not None:
        return (xray_ping, True, True, None)
    return (None, False, False, None)

def extract_host_port(config: str) -> Tuple[Optional[str], Optional[int]]:
    if config.startswith('vless://'):
        m = re.search(r'vless://[^@]+@([^:?#]+):(\d+)', config)
        if m: return m.group(1), int(m.group(2))
    elif config.startswith('vmess://'):
        try:
            d = json.loads(base64.b64decode(config[8:] + '=' * (4 - len(config[8:]) % 4)))
            return d.get('add'), int(d.get('port', 0))
        except: pass
    elif config.startswith('trojan://'):
        m = re.search(r'trojan://[^@]+@([^:?#]+):(\d+)', config)
        if m: return m.group(1), int(m.group(2))
    return None, None

def get_protocol(config: str) -> str:
    if config.startswith('vless://'): return "VLESS"
    elif config.startswith('vmess://'): return "VMESS"
    elif config.startswith('trojan://'): return "TROJAN"
    return ""