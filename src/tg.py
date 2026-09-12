#!/usr/bin/env python3
import os
import requests
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MSK_TZ = timezone(timedelta(hours=3))

class TelegramBot:
    def __init__(self):
        self.start_time = None
        self.last_edit = 0

    def _call(self, method: str, payload: dict) -> Optional[int]:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return None
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
            payload["chat_id"] = TELEGRAM_CHAT_ID
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
        except: pass
        return None

    def send_msg(self, text: str, parse_mode: str = "HTML") -> Optional[int]:
        return self._call("sendMessage", {"text": text, "parse_mode": parse_mode, "disable_web_page_preview": True})

    def edit_msg(self, msg_id: int, text: str, parse_mode: str = "HTML") -> bool:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}, timeout=10)
            return True
        except: return False

    def send_start(self) -> Optional[int]:
        now = datetime.now(MSK_TZ).strftime("%H:%M:%S")
        msg = f"🤖 <b>LetoVPN</b>\n<i>started at {now}</i>"
        self.start_time = time.time()
        return self.send_msg(msg)

    def update_progress(self, msg_id: int, checked: int, total: int, found: int, elapsed: float):
        now = datetime.now(MSK_TZ).strftime("%H:%M:%S")
        pct = int(checked / total * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        sec = int(elapsed)
        msg = f"🔍 <b>LetoVPN</b>\n{bar} {pct}%\n\n📊 {checked}/{total}\n🎯 {found} working\n⏱ {sec}s\n🕒 {now}"
        if time.time() - self.last_edit > 2:
            self.edit_msg(msg_id, msg)
            self.last_edit = time.time()

    def send_final(self, total: int, found: int, fast: int, elapsed: float, pass1: int = 0, pass2: int = 0):
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        msg = f"✅ <b>LetoVPN Done</b>\n\n📊 Checked: {total}\n🎯 Working: {found}"
        if pass1 and pass2:
            pct = int(pass2 / max(pass1, 1) * 100)
            msg += f" ({pct}% confirmed)\n"
        else:
            msg += "\n"
        msg += f"⚡ Fast: {fast}\n⏱ Time: {time_str}\n"
        repo = os.getenv("GITHUB_REPOSITORY", "adop1344-bot/LetoVPN_free")
        msg += f"\n📁 <a href='https://raw.githubusercontent.com/{repo}/main/configs_hiddify.txt'>configs</a> | <a href='https://raw.githubusercontent.com/{repo}/main/ru_hiddify.txt'>ru</a>"
        self.last_edit = 0
        return self.send_msg(msg)