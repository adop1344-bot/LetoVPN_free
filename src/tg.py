#!/usr/bin/env python3
import os
import requests
from typing import Optional

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class TelegramBot:
    def __init__(self):
        self.message_id = None
        
    def send(self, message: str) -> Optional[int]:
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return None
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
        except:
            pass
        return None
    
    def edit(self, message_id: int, message: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": message, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=10)
        except:
            pass
    
    def send_start(self, total: int):
        msg = f"🚀 <b>LetoVPN</b>\n📊 Загружено конфигов: {total}\n🔄 Начинаю проверку..."
        self.message_id = self.send(msg)
    
    def update(self, checked: int, total: int, found: int, top: list, elapsed: float):
        msg = f"<b>🚀 LetoVPN</b>\n"
        msg += f"📊 Проверено: {checked}/{total}\n"
        msg += f"✅ Найдено: {found}\n"
        msg += f"⏱ Время: {elapsed:.0f} сек\n\n"
        msg += "<b>🏆 ТОП-10 (самые быстрые):</b>\n"
        
        if top:
            for i, (flag, protocol, ping, lightning) in enumerate(top, 1):
                msg += f"{i}. {flag}{protocol} {ping:.0f}ms"
                if lightning:
                    msg += " ⚡"
                msg += "\n"
        else:
            msg += "⏳ Пока ни одного..."
        
        if self.message_id:
            self.edit(self.message_id, msg)
    
    def send_final(self, total: int, found: int, fast: int, elapsed: float, top: list):
        msg = f"<b>✅ LetoVPN: Готово!</b>\n"
        msg += f"📊 Всего проверено: {total}\n"
        msg += f"🎯 Рабочих конфигов: {found}\n"
        msg += f"⚡ Быстрых (пинг &lt;200ms): {fast}\n"
        msg += f"⏱ Время: {elapsed:.1f} сек\n\n"
        msg += f"<b>🏆 ТОП-10:</b>\n"
        
        for i, (flag, protocol, ping, lightning) in enumerate(top, 1):
            msg += f"{i}. {flag}{protocol} {ping:.0f}ms"
            if lightning:
                msg += " ⚡"
            msg += "\n"
        
        msg += f"\n📁 Файлы: configs.txt, ru.txt, protocols/"
        self.send(msg)
