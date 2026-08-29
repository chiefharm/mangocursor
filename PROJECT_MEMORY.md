# MangoCursor — база знаний проекта (память для AI)

> **Для AI:** в начале **любой** новой сессии по этому проекту прочитай этот файл **целиком**, затем `SESSION_LOG.md`.  
> Копия на VPS: `/opt/mango-pipeline/PROJECT_MEMORY.md`

---

## Цель

Автоматизировать **контроль качества звонков** сети салонов **«SOCO / Сока»** (Mango Office).

**Задача владельца (личка Telegram — `TELEGRAM_CHAT_ID` в `.env`, не в git):**
1. Каждый день забирать звонки из Mango (два аккаунта: Москва + Красноярск)
2. Расшифровывать (Yandex SpeechKit)
3. **Отправлять в Telegram только косячные** + сомнительные
4. Хорошие звонки **не присылать**
5. Работать **без ПК** (VPS Amsterdam)

---

## Два салона (multi-site)

| site_id | Подпись в сообщениях | ЛС Mango | Часовой пояс |
|---------|----------------------|----------|--------------|
| `moscow` | расшифровка звонков SOCO Москва | **16958477** | Europe/Moscow |
| `krasnoyarsk` | расшифровка звонков SOCO Красноярск | **16719904** | Asia/Krasnoyarsk |

Конфиг: `site_config.py`, переменные `MANGO_SITES=moscow,krasnoyarsk`, `SITE_*` в `.env`.  
Ключи API **только в `.env` на VPS**, не в git и не в этот файл.

### Красноярск — один номер, добавочные (филиалы)

Городской **(391) 269-90-73**. В API: `line_number=73912699073`, филиал = `to_extension`.

| Доб. | Точка | Учитывать |
|------|-------|-----------|
| **05** | Новосибирская | да |
| **12** | Дубровинского | да |
| **25** | Весны | да |
| **97** | Горького | **нет** (филиал закрыт) |
| **269-90-78**, доб. 14/105/112/197 | «Потерянные» | **нет** |

Логика: `site_lines.py` → `is_tracked_call()`, `branch_label()`.

---

## Telegram — маршрутизация (актуально 04.07.2026)

Бот: **chiefharmcursor** (`TELEGRAM_BOT_TOKEN` в `.env`).

| site | Личка | Группа |
|------|-------|--------|
| **moscow** | `TELEGRAM_CHAT_ID` | `SITE_MOSCOW_GROUP_CHAT_IDS` в `.env` |
| **krasnoyarsk** | `TELEGRAM_CHAT_ID` | `SITE_KRASNOYARSK_GROUP_CHAT_IDS` в `.env` |

- Каждый город → **своя** группа + **личка** (оба получают копию своего города).
- **`TELEGRAM_EXTRA_CHAT_IDS` не использовать** — иначе группы смешиваются.
- Функция: `telegram_notify.site_chat_ids(site)`.
- Отправка **только с VPS** (Telegram заблокирован с ПК в РФ).

**Не путать:** `@hermes_cursor_agent_bot` — отдельный Hermes/cursor-tg бот.

---

## Что отправлять / не отправлять

### Отправлять (`verdict: bad` / `uncertain`)

См. `call_qc.py` → `assess_call()` → `should_send`.

### НЕ отправлять (`verdict: good`)

Запись подтверждена, перенос согласован, сервисный звонок без проблем.

---

## Формат Telegram (`telegram_format.py`)

```
расшифровка звонков SOCO Красноярск

3 июля · 07:09
входящий · 7XXXXXXXXX
Точка: Весны (доб. 25)
Категория: …

Ошибка: …

Проблема:
…
```

+ DOCX с расшифровкой (без цитат в тексте сообщения).  
Сводка дня в начале (`format_day_summary()`).  
Если Mango не отдал статистику (баланс / 429 / пустой ответ) — в сводке **«🔴 Статистика недоступна»** (жирный HTML), а не «Входящих: 0».

---

## Расшифровки — постобработка (`transcript_utils.py`)

**Актуально с 04.07.2026:**

1. **Без ролей** «Администратор» / «Клиент» в DOCX — только текст реплик (`transcript_paragraphs()`).
2. **Цифры цифрами:** `семнадцать ноль ноль` → `17:00`, `пятнадцать пятнадцать` → `15:15`, отдельные числа прописью → цифры.
3. **Дедупликация** повторов Yandex в `refine_segments()`.
4. QC (`call_qc.py`) работает по **полному тексту** диалога (роли не нужны).

> Старые функции `apply_speaker_roles` / `apply_content_roles` в коде остались, но **не вызываются** из `refine_segments`.

---

## Архитектура

```
MANGO_SITES (moscow + krasnoyarsk)
        ↓
mango_sync.py --site X --yandex  →  HTML в calls/{site}/
        ↓
call_qc.py
        ↓
daily_pipeline.py / send_day_to_telegram.py --site X
        ↓
Telegram: сводка + bad/uncertain + DOCX
```

**Mango API только чтение:** `stats/request`, `stats/result`, `queries/recording/post` (download).  
Настройки АТС **не меняем**.

**Yandex SpeechKit** вместо Mango SA (~0.2₽/мин).

---

## VPS (Timeweb Amsterdam)

| Параметр | Значение |
|----------|----------|
| IP | только в `deploy/vps.host` (файл **не в git**, см. `deploy/vps.host.example`) |
| Путь | `/opt/mango-pipeline` |
| SSH | `ssh -i ~/.ssh/id_ed25519 root@$(cat deploy/vps.host)` |
| Таймер | **10:00 МСК** (`mango-pipeline.timer`, OnCalendar 07:00 UTC) |

`daily_pipeline.py` обрабатывает **оба** site за один запуск; «вчера» считается по TZ каждого site.

**Важно:** пайплайн шлёт только звонки **за вчера** (префикс `YYYY-MM-DD__` в имени HTML), не весь архив.

---

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `site_config.py` | Два Mango-аккаунта, пути, группы Telegram |
| `site_lines.py` | Филиалы Красноярска, фильтр добавочных |
| `telegram_notify.py` | `site_chat_ids(site)` — маршрутизация |
| `telegram_format.py` | Формат сообщений + `site_label`, `branch` |
| `call_qc.py` | QC, сводка дня |
| `transcript_utils.py` | Парсинг HTML, цифры, без ролей |
| `daily_pipeline.py` | Автоматика (multi-site) |
| `send_day_to_telegram.py` | Ручная отправка `--site moscow\|krasnoyarsk` |
| `mango_sync.py` | Синк + `--site` + фильтр филиалов |
| `data/sent_calls_{site_id}.json` | Уже отправленные (на VPS) |

Память AI: `PROJECT_MEMORY.md`, `SESSION_LOG.md`, `CODE_MAP.md`, `AGENTS.md`.

---

## Команды (VPS)

```bash
cd /opt/mango-pipeline

# Синк + STT за день (Красноярск)
.venv/bin/python mango_sync.py --site krasnoyarsk --date 2026-07-03 --yandex

# Отправить косячные за день
.venv/bin/python send_day_to_telegram.py --site moscow --date 2026-07-03
.venv/bin/python send_day_to_telegram.py --site krasnoyarsk --date 2026-07-03

# Автоматика (оба города)
.venv/bin/python daily_pipeline.py --base-dir /opt/mango-pipeline --mango-sync --mango-days 1

systemctl status mango-pipeline.timer
```

---

## Известные инциденты

| Период | Что |
|--------|-----|
| 26.06–02.07 | Записей Mango нет в API — **звонки не работали** (не баг нашего кода). 25.06 записи есть. |
| 25–26.06 | Перебои мобильного интернета Москва (не сбой Mango). |
| 01–03.07 | Timeweb Qupra NL — VPS недоступен, восстановлен 03.07. |
| 03.07 | Баг: пайплайн слал **весь архив** (апрель–май) → исправлено: только вчера. |

---

## История решений (кратко)

| Дата | Решение |
|------|---------|
| 2026-06 | Yandex STT, QC-фильтр, VPS Amsterdam |
| 2026-07-03 | Формат Telegram, роли STT (потом отменены) |
| 2026-07-04 | **Второй аккаунт Красноярск**, multi-site |
| 2026-07-04 | Маршрутизация Telegram по группам |
| 2026-07-04 | **Убраны роли** в DOCX, усилена нормализация цифр |
| 2026-07-04 | Фильтр филиалов Красноярска (05/12/25) |

---

## Отчёты выручки (с 23.07.2026)

Скрипт: `revenue_report.py`  
Cron: `0 5 * * *` (Europe/Moscow) → `deploy/install_revenue_cron.sh`  
Куда: только личка `TELEGRAM_CHAT_ID` (пока без групп).

Каждый запуск **скачивает свежие** Excel с публичных ссылок Яндекс.Диска (`REVENUE_YADISK_KRAS`, `REVENUE_YADISK_MSK`), считает, шлёт, временные файлы удаляет.

Сообщения:
1–3. Красноярск: Дубровинского / Новосибирская / Весны  
4. Москва: Фили  

Прогноз конца месяца = среднее из:
- текущий средний день × оставшиеся дни  
- сумма факта за тот же «хвост» месяца в −1 мес  
- то же за −2 мес  

Плюс сравнение MTD с −1/−2 мес и с тем же месяцем год назад.

---

## Ограничения

- Telegram с ПК РФ — таймаут → только VPS
- QC — эвристика; владелец дообучает по «сомнительным»
- Yandex STT склеивает реплики → ответ админа может быть в одной строке с клиентом
- ~30 записей/день Красноярск могут не расшифроваться (короткие / лимиты Yandex)

---

## Личные финансы (не салон)

Отдельный сайт в репозитории: каталог `personal-finance/`. Выписки, разнесение переводов без статьи. Цель месяца и отчёт в **отдельную Telegram-группу** (итоги, всплески, советы, кнопки) — после того как переводы разнесены. **Не использует** Mango, группы SOCO и `daily_pipeline`.

**Откуда выписки:** папка Google Drive  
https://drive.google.com/drive/folders/1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj  

Имена файлов **не переименовывать**. Период и «что новее» — по датам операций внутри PDF/CSV/Excel. Повторная загрузка того же периода не двоит строки. PDF Альфа: копилка и внутрибанковские переводы → «между своими» без очереди; HOLD (неподтверждённые) пропускаются. Подтянуть папку: кнопка на сайте или `python -m app.pull`.

---

*Последнее обновление: 2026-08-29*
