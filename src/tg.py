#!/usr/bin/env python3
import os
import requests
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MSK_TZ = timezone(timedelta(hours=3))

def now_msk():
    return datetime.now(MSK_TZ)

class TelegramBot:
    def __init__(self):
        self.start_time = None
        
    def send(self, message: str) -> Optional[int]:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return None
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
        except:
            pass
        return None
    
    def send_start(self):
        now = now_msk().strftime("%H:%M")
        msg = f"🚀 <b>LetoVPN</b>\n<i>test started... {now}</i>"
        self.start_time = time.time()
        return self.send(msg)
    
    def send_final(self, total: int, found: int, fast: int, elapsed: float):
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        time_str = f"{minutes} min {seconds} sec" if minutes > 0 else f"{seconds} sec"
        
        msg = (
            f"<b>✅ LetoVPN</b>\n\n"
            f"📊 <b>проверенно:</b> {total}\n"
            f"🎯 <b>Рабочих:</b> {found}\n"
            f"⚡ <b>Быстрых:</b> {fast}\n"
            f"⏱ <b>Время заняло:</b> {time_str}"
        )
        
        repo = os.getenv("GITHUB_REPOSITORY", "adop1344-bot/LetoVPN_free")
        msg += f"\n\n📁 <b>Скачать:</b>\n"
        msg += f"• <a href='https://raw.githubusercontent.com/{repo}/main/configs_hiddify.txt'>configs_hiddify.txt</a>\n"
        msg += f"• <a href='https://raw.githubusercontent.com/{repo}/main/ru_hiddify.txt'>ru_hiddify.txt</a>"
        
        return self.send(msg)