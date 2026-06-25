# MangoCursor — база знаний проекта

> **Для AI:** в начале любой новой сессии по этому проекту прочитай этот файл целиком.

## Цель проекта

Автоматизировать контроль качества звонков **салона красоты «Сока»** (Mango Office, речевая аналитика).

**Задача:** находить «плохие» и важные для разбора звонки, формировать расшифровку с коротким комментарием о проблеме и отправлять владельцу в **Telegram** — чтобы работало **без включённого ПК** (через VPS).

---

## Что считаем «плохим» / важным звонком

| Категория | Маркеры |
|-----------|---------|
| Недовольство клиента | недовол, жалоб, претенз, извин |
| Отказ в услуге | не делаем, отказ |
| Техсбой записи | ошибка, невозможно записаться, техподдержка |
| Цена без записи | сколько стоит → ушёл без записи |
| Не закрыт в запись | перезвоню, подумаю, не смогу |
| Перенос/отмена | отменить, перенести, перезаписаться |
| Неудобное время | не устраивает, позднее время |
| Новый клиент | первый раз |

---

## Формат данных

- **Вход:** HTML-расшифровки из Mango Office (имя вида `2026-04-10__17-47-57__79164957110__админ1.html`)
- **Агрегированный CSV** (`2026-04-29_13-51-08.csv`) — только сводка по дням, **без** полных расшифровок; колонка «Жалобы и претензии (AI)» > 0% — критерий для отчёта, но не для per-call отправки
- **Выход в Telegram:** **DOCX** (лучше всего открывается на iPhone). TXT и HTML в Telegram на iOS часто показываются пустыми

---

## Архитектура

```
Mango Office (ручной экспорт HTML)
        ↓
  GitHub mangocursor  или  папка incoming на VPS
        ↓
  daily_pipeline.py (VPS, cron 20:00 МСК)
        ↓
  auto-select проблемных → DOCX → Telegram
```

**Полная автоматизация из Mango API** — пока не подключена (дорого/сложно); обходной путь — ручной экспорт HTML → git push или upload на сервер.

---

## Репозиторий и пути

| Что | Где |
|-----|-----|
| Локальный проект | `C:\Users\chief\Desktop\cursor\mangocursor` |
| GitHub | https://github.com/chiefharm/mangocursor |
| Ветка | `master` |

---

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `daily_pipeline.py` | **Главный скрипт для VPS:** автоотбор, DOCX, Telegram, учёт уже отправленных |
| `send_calls_to_telegram.py` | Отправка по списку `selected_calls.json` (локально / Windows) |
| `process_calls_to_telegram.ps1` | PowerShell-версия для Windows |
| `selected_calls.json` | Ручной список звонков для отправки |
| `deploy/vps_install.sh` | Установка на VPS + systemd timer |
| `.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (не коммитить!) |
| `data/sent_calls.json` | На VPS: какие файлы уже отправлены |

---

## Telegram

- **Бот для расшифровок звонков** — отдельный бот (токен в `.env`)
- **@hermes_cursor_agent_bot** — другой бот (мост cursor-tg на VPS), **не путать** с ботом расшифровок
- `TELEGRAM_CHAT_ID` владельца: личный чат (числовой id)

Секреты только в `.env`, никогда не коммитить.

---

## VPS (Timeweb)

| Параметр | Значение |
|----------|----------|
| IP | `72.56.249.113` |
| ОС | Ubuntu 24.04 |
| Путь пайплайна | `/opt/mango-pipeline` |
| cursor-tg (Hermes) | `/opt/cursor-tg` |
| Расписание | ежедневно 20:00 МСК (`mango-pipeline.timer`) |

**Статус на 2026-06:** SSH по ключу `chief-vps` может не работать после переустановки сервера — нужно заново добавить публичный ключ в панели Timeweb.

---

## Команды (локально, Windows)

```powershell
cd C:\Users\chief\Desktop\cursor\mangocursor

# Подготовка без отправки
python daily_pipeline.py --dry-run

# Отправка по selected_calls.json
python send_calls_to_telegram.py --send-as-files
```

## Команды (VPS)

```bash
# После deploy/vps_install.sh
nano /opt/mango-pipeline/.env
/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --dry-run
systemctl start mango-pipeline.service
systemctl status mango-pipeline.timer
```

---

## Что уже сделано

- [x] Разбор 41 HTML-расшифровки, категории проблемных звонков
- [x] Отправка в Telegram (текст, TXT, HTML, DOCX) — **DOCX на iPhone работает лучше всего**
- [x] `daily_pipeline.py` + деплой-скрипт для VPS
- [x] Push в GitHub `chiefharm/mangocursor`
- [ ] Завершить деплой на VPS (нужен SSH-ключ)
- [ ] Автозагрузка расшифровок из Mango API (ждём ответ поддержки Mango)

---

## Типичные запросы владельца

1. «Проверь новые звонки по критериям» → auto-select / grep по HTML → список + комментарии
2. «Отправь в Telegram» → DOCX + короткий комментарий перед каждым файлом
3. «Настрой автоматом каждый день» → VPS + `daily_pipeline.py` + cron
4. «Сохрани в GitHub» → commit + push (не трогать `.env`)

---

## Ограничения и нюансы

- Python на Windows через Store иногда нестабилен; для VPS — `python3` + venv
- DOCX на Windows: Word COM; на Linux: `python-docx`
- Не использовать длинные сообщения в Telegram для iPhone — только DOCX или короткие части
- Mango CSV не заменяет HTML для полных расшифровок

---

*Последнее обновление: 2026-06-25*
