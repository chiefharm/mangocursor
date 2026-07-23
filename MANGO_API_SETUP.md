# Подключение Mango API

## Что уже работает в проекте

| Компонент | Файл | Назначение |
|-----------|------|------------|
| VPBX-клиент | `mango_vpbx.py` | История звонков, ссылки на записи |
| Синхронизация | `mango_sync.py` | Забирает звонки за день, сохраняет HTML |
| Webhook-сервер | `mango_webhook_server.py` | Принимает POST от Mango, кладёт JSON в `data/webhooks/` |
| Пайплайн | `daily_pipeline.py --mango-sync` | Синк → отбор → DOCX → Telegram |

## Шаг 1. Ключи API

1. Откройте [личный кабинет Mango](https://lk.mango-office.ru/) → **Интеграции** → **API коннектор**.
2. Скопируйте **ключ API** и **соль (salt)**.
3. Добавьте в `.env`:

```env
MANGO_VPBX_API_KEY=ваш_ключ
MANGO_VPBX_API_SALT=ваша_соль
MANGO_LINE_NUMBER=sip:so1297co@vpbx400310395.mangosip.ru
```

## Шаг 2. Проверка синхронизации

```powershell
cd C:\Users\chief\Desktop\cursor\mangocursor
python mango_sync.py --days 1
```

или вместе с пайплайном:

```powershell
python daily_pipeline.py --mango-sync --dry-run
```

## Важно про расшифровки

**Публичный VPBX API** отдаёт:

- список звонков (`stats/request` + `stats/result`);
- аудиозаписи (`queries/recording/post`).

**Текст расшифровки из речевой аналитики** в открытой документации VPBX **не описан**. Mango передаёт текст в CRM (amoCRM, Битрикс24) или через **кастомный API речевой аналитики** — его нужно запросить у поддержки.

Поэтому сейчас три пути к тексту:

1. **Webhook** — если Mango/интегратор шлёт JSON с полем `transcript` / `dialog` на ваш URL.
2. **SA endpoint** — после ответа поддержки прописать `MANGO_SA_TRANSCRIPT_ENDPOINT` в `.env`.
3. **Ручной HTML-экспорт** — как раньше (файлы в корне проекта).

## Шаг 3. Webhook на VPS (рекомендуется)

На сервере:

```bash
/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/mango_webhook_server.py \
  --host 0.0.0.0 --port 8787 --token YOUR_TOKEN
```

В Mango → **Вебхуки** укажите URL:

```text
http://OLD_VPS_IP:8787/?token=YOUR_TOKEN
```

Настройте событие «завершение звонка» / «запись готова» и по возможности поля с текстом расшифровки.

Полезные IP Mango для firewall: `81.88.80.132`, `81.88.80.133`, `81.88.82.36`.

## Шаг 4. Запрос в поддержку Mango

Скопируйте и отправьте в чат поддержки из ЛК:

```text
Здравствуйте!

Нужна автоматическая выгрузка текстовых расшифровок речевой аналитики по API
для собственного сервиса (не CRM).

Виртуальная АТС: vpbx400310395, салон «Сока».

Прошу подсказать:
1) Есть ли API-метод для получения полной расшифровки диалога (Сотрудник/Клиент) по entry_id или recording_id?
2) Можно ли настроить webhook с текстом расшифровки и AI-тегами на наш URL?
3) Какие поля и формат JSON в таком webhook?

Цель: ежедневно забирать расшифровки проблемных звонков и отправлять владельцу в Telegram.

Спасибо!
```

Когда пришлют endpoint — добавьте в `.env`:

```env
MANGO_SA_TRANSCRIPT_ENDPOINT=путь/к/методу
```

## Шаг 5. Автоматизация на VPS

```bash
/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py \
  --base-dir /opt/mango-pipeline --mango-sync --mango-days 1
```

## Структура данных

```text
data/
  calls/           # метаданные звонков без расшифровки (entry_id.json)
  calls_index.json # связь entry_id → html-файл
  webhooks/        # сырые JSON от Mango
```
