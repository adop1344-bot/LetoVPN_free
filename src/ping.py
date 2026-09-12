#!/usr/bin/env python3
import socket, time, re, base64, json, shutil, subprocess, os, random
import socks  # PySocks
from typing import Tuple, Optional

XRAY_AVAILABLE = False
REAL_PING_URL = "https://www.gstatic.com/generate_204"

def init_xray():
    global XRAY_AVAILABLE
    if shutil.which("xray"):
        try:
            subprocess.run(["xray", "version"], capture_output=True, timeout=5)
            XRAY_AVAILABLE = True; print("Xray ready"); return True
        except: pass
    print("Xray not found"); return False

def xray_check(config: str, timeout: int) -> Optional[float]:
    if not XRAY_AVAILABLE: return None
    config_path = None
    sock_port = random.randint(30000, 50000)
    try:
        import tempfile, json as j
        xc = convert_to_xray_config(config, sock_port)
        if not xc: return None
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            j.dump(xc, f); config_path = f.name

        start = time.time()
        proc = subprocess.Popen(["xray", "run", "-config", config_path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3.0)

        # Проверяем что Xray жив
        if proc.poll() is not None:
            try: os.unlink(config_path)
            except: pass
            return None

        # Проверяем что порт реально слушается
        try:
            s = socket.create_connection(("127.0.0.1", sock_port), timeout=2)
            s.close()
        except:
            proc.kill(); proc.wait()
            try: os.unlink(config_path)
            except: pass
            return None

        # Делаем запрос через SOCKS5
        try:
            orig = socket.socket
            s = socks.socksocket()
            s.set_proxy(socks.SOCKS5, "127.0.0.1", sock_port)
            s.settimeout(timeout)
            s.connect(("www.gstatic.com", 443))
            
            # SSL handshake
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ss = ctx.wrap_socket(s, server_hostname="www.gstatic.com")
            
            # HTTP GET
            ss.send(b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\nConnection: close\r\n\r\n")
            resp = ss.recv(1024).decode(errors='ignore')
            ss.close()
            
            if '204' in resp[:50] or '200' in resp[:50]:
                elapsed = (time.time() - start) * 1000
                proc.kill(); proc.wait()
                try: os.unlink(config_path)
                except: pass
                return elapsed
        except:
            pass

        proc.kill(); proc.wait()
        try: os.unlink(config_path)
        except: pass
        return None
    except:
        if config_path:
            try: os.unlink(config_path)
            except: pass
        return None

def convert_to_xray_config(line: str, sock_port: int = 1080) -> Optional[dict]:
    import urllib.parse
    def ib(p): return [{"port": p, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}]
    if line.startswith('vless://'):
        m = re.search(r'vless://([^@]+)@([^:]+):(\d+)(.*)', line)
        if not m: return None
        u, h, p, qs = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        q = urllib.parse.parse_qs(urllib.parse.urlparse("?" + qs.lstrip("?#&")).query)
        ss = {"network": q.get("type", ["tcp"])[0], "security": q.get("security", ["none"])[0]}
        sec = q.get("security", ["none"])[0]
        if sec in ["tls", "reality"]:
            tls = {"serverName": q.get("sni", [h])[0], "fingerprint": q.get("fp", ["chrome"])[0] if q.get("fp") else "chrome"}
            if sec == "reality":
                tls["show"] = False; tls["publicKey"] = q.get("pbk", [""])[0]
                tls["shortId"] = q.get("sid", [""])[0]; tls["spiderX"] = q.get("spx", ["/"])[0]
            ss["tlsSettings"] = tls
        return {"log": {"loglevel": "none"}, "inbounds": ib(sock_port),
                "outbounds": [{"protocol": "vless",
                               "settings": {"vnext": [{"address": h, "port": p,
                                                         "users": [{"id": u,
                                                                     "encryption": q.get("encryption", ["none"])[0],
                                                                     "flow": q.get("flow", [""])[0]}]}]},
                               "streamSettings": ss}]}
    elif line.startswith('vmess://'):
        try:
            d = json.loads(base64.b64decode(line[8:] + '=' * (4 - len(line[8:]) % 4)))
            ss = {"network": d.get("net", "tcp"), "security": d.get("tls", "none")}
            if d.get("tls") == "tls":
                ss["tlsSettings"] = {"serverName": d.get("sni", d.get("host", d.get("add", ""))),
                                       "fingerprint": d.get("fp", "chrome")}
            return {"log": {"loglevel": "none"}, "inbounds": ib(sock_port),
                    "outbounds": [{"protocol": "vmess",
                                   "settings": {"vnext": [{"address": d.get("add", ""),
                                                             "port": int(d.get("port", 0)),
                                                             "users": [{"id": d.get("id", ""),
                                                                         "alterId": int(d.get("aid", 0)),
                                                                         "security": d.get("scy", "auto")}]}]},
                                   "streamSettings": ss}]}
        except: return None
    elif line.startswith('trojan://'):
        m = re.search(r'trojan://([^@]+)@([^:]+):(\d+)(.*)', line)
        if not m: return None
        pw, h, p, qs = m.group(1), m.group(2), int(m.group(3)), m.group(4) or ""
        q = urllib.parse.parse_qs(urllib.parse.urlparse("?" + qs.lstrip("?#&")).query)
        ss = {"network": q.get("type", ["tcp"])[0], "security": "tls",
              "tlsSettings": {"serverName": q.get("sni", [h])[0],
                              "fingerprint": q.get("fp", ["chrome"])[0] if q.get("fp") else "chrome"}}
        return {"log": {"loglevel": "none"}, "inbounds": ib(sock_port),
                "outbounds": [{"protocol": "trojan",
                               "settings": {"servers": [{"address": h, "port": p, "password": pw}]},
                               "streamSettings": ss}]}
    return None

def verify_config(config: str, timeout: float) -> Tuple[Optional[float], bool, bool, Optional[float]]:
    if not XRAY_AVAILABLE: return (None, False, False, None)
    x = xray_check(config, int(timeout))
    if x is not None: return (x, True, True, None)
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