# 🚀 LetoVPN_free

**Автоматический сборщик и проверщик VPN-конфигов (VLESS, VMESS, TROJAN)**

[![GitHub Actions](https://github.com/adop1344-bot/LetoVPN_free/actions/workflows/hourly-test.yml/badge.svg)](https://github.com/adop1344-bot/LetoVPN_free/actions/workflows/hourly-test.yml)

---

## 📌 О проекте

LetoVPN_free — это автоматический сервис, который:

- 🔍 **Собирает** конфиги из открытых источников
- ✅ **Проверяет** их работоспособность (TCP + HTTP прокси)
- 🌍 **Определяет** страну и город сервера
- ⚡ **Сортирует** по скорости и протоколам
- 📁 **Обновляет** файлы каждые 2 часа

---

## 📥 Скачать конфиги

### 🔹 Все страны
```

https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/configs.txt

```

### 🔹 Только Россия
```

https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/ru.txt

```

### 🔹 По протоколам
| Протокол | Ссылка |
|----------|--------|
| **VLESS** | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/protocols/VLESS.txt` |
| **VMESS** | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/protocols/VMESS.txt` |
| **TROJAN** | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/protocols/TROJAN.txt` |

### 🔹 Разбивка по 200 конфигов
| Файл | Ссылка |
|------|--------|
| checked1.txt | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/checked1.txt` |
| checked2.txt | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/checked2.txt` |
| ... | ... |
| checked10.txt | `https://raw.githubusercontent.com/adop1344-bot/LetoVPN_free/main/checked10.txt` |

---

## 🛠️ Как использовать в Hiddify

1. Открой Hiddify
2. Нажми **➕ Добавить подписку**
3. Вставь одну из ссылок выше
4. Нажми **Обновить**

---

## 📊 Формат названий конфигов

```

🇺🇸 США sni=ya.ru
🇷🇺 Россия ⚡ sni=vk.com
🇩🇪 Германия sni=no-sni

```

| Символ | Значение |
|--------|----------|
| 🇺🇸 | Флаг страны |
| ⚡ | Быстрый пинг (<200 мс) |
| sni=... | SNI сервера |

---

## 🔧 Технические детали

| Параметр | Значение |
|----------|----------|
| **Источников** | 10+ публичных репозиториев |
| **Проверка** | TCP ping + HTTP GET через прокси |
| **Потоков** | 500 |
| **Обновление** | Каждые 2 часа (GitHub Actions) |
| **Определение страны** | GeoIP2 + домены + ключевые слова |

---

## 📁 Структура репозитория

```

LetoVPN_free/
├── configs.txt              # Все страны
├── ru.txt                   # Только Россия
├── checked1-10.txt          # Разбивка по 200 конфигов
├── protocols/
│   ├── VLESS.txt            # Только VLESS
│   ├── VMESS.txt            # Только VMESS
│   └── TROJAN.txt           # Только TROJAN
├── src/                     # Исходный код
├── sources.txt              # Источники конфигов
├── flags.txt                # Коды стран → флаги
├── keywords.txt             # Ключевые слова
├── cities.txt               # Города по IP
├── domains.txt              # Домены → страны
└── .github/workflows/       # GitHub Actions

```

---

## 📢 Канал в Telegram

Подписывайся на обновления: [@LetoVPN_free](https://t.me/LetoVPN_free)

---

## 📜 Лицензия

MIT License — используй как хочешь! 🚀

---

## ⚠️ Отказ от ответственности

Проект предназначен для образовательных целей. Используйте на свой страх и риск. Ответственность за использование лежит на пользователе.
```
