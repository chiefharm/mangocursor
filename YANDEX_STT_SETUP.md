# Mango MP3 → Yandex SpeechKit

Обходной путь, если Mango не отдаёт текст расшифровки по API:

```
Mango API (MP3) → Yandex SpeechKit STT v3 → HTML → daily_pipeline → Telegram
```

## Стоимость (ориентир)

Yandex SpeechKit: порядка **0,16–0,25 ₽/мин** распознавания (зависит от тарифа).  
Звонок ~1 мин ≈ **0,2 ₽**. 7 звонков/день ≈ **40–50 ₽/мес**.

## Шаг 1. Ключ Yandex Cloud

1. [console.yandex.cloud](https://console.yandex.cloud/) → каталог (folder).
2. **SpeechKit** → включить сервис.
3. **Сервисный аккаунт** → роль `ai.speechkit-stt.user` → **API-ключ**.
4. В `.env`:

```env
YANDEX_STT_ENABLED=1
YANDEX_SPEECHKIT_API_KEY=ваш_api_ключ
YANDEX_FOLDER_ID=b1gxxxxxxxx   # опционально, но иногда нужен
```

## Шаг 2. Тест на одном дне

```powershell
cd C:\Users\chief\Desktop\cursor\mangocursor
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" mango_sync.py --days 1 --yandex
```

Кэш MP3 и JSON: `data/yandex_cache/`.  
HTML расшифровок — в корне проекта (как раньше).

## Шаг 3. Пайплайн

```powershell
python daily_pipeline.py --mango-sync --dry-run
```

С `YANDEX_STT_ENABLED=1` синк автоматически идёт через Yandex.

## Нюансы

- **Спикеры:** Yandex помечает «Спикер 1 / 2», не «Сотрудник / Клиент» как в Mango SA. Для отбора проблемных звонков по ключевым словам — достаточно.
- **Качество:** телефония 8 kHz — норм для SpeechKit, но может отличаться от Mango SA.
- **Повторный запуск:** расшифровка кэшируется в `data/yandex_cache/{entry_id}.json` — повторно Yandex не дергается.

## Файлы

| Файл | Роль |
|------|------|
| `yandex_stt.py` | Клиент SpeechKit v3 async |
| `mango_vpbx.py` | `download_recording()` |
| `mango_sync.py --yandex` | Полный цикл за день |
