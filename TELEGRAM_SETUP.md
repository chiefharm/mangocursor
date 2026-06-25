# Подключение Telegram-бота для расшифровок звонков

В проекте уже есть скрипт `send_calls_to_telegram.py`, который берет звонки из `selected_calls.json`, парсит HTML-файлы расшифровок и отправляет их в Telegram.

## 1) Создай бота и получи токен

1. Открой [@BotFather](https://t.me/BotFather).
2. Команда `/newbot`.
3. Скопируй `TELEGRAM_BOT_TOKEN`.

## 2) Получи chat_id

1. Напиши своему боту любое сообщение (например, `start`).
2. В браузере открой:
   `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`
3. Найди поле `chat -> id` (для личного чата обычно положительное число, для группы часто отрицательное).

## 3) Заполни `.env`

1. Скопируй `.env.example` в `.env`.
2. Впиши реальные значения:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## 4) Запуск

Сначала проверка без отправки:

```powershell
py -3 .\send_calls_to_telegram.py --dry-run
```

Реальная отправка:

```powershell
py -3 .\send_calls_to_telegram.py
```

## 5) Откуда берутся звонки

- Скрипт читает список из `selected_calls.json`.
- Каждый элемент должен содержать:
  - `file` — имя HTML-файла звонка;
  - `category` — категория/тег звонка.

Если файла нет или расшифровка не распарсилась, скрипт покажет предупреждение и перейдет к следующему звонку.
