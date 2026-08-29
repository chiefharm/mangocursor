# Карта кода MangoCursor

> Индекс файлов. Полный код — репозиторий / VPS `/opt/mango-pipeline/`.  
> Копия на VPS: `/opt/mango-pipeline/CODE_MAP.md`

---

## Ядро пайплайна

| Файл | Назначение |
|------|------------|
| `site_config.py` | `SiteConfig`, `load_sites()`, пути `calls/{site}/`, группы TG |
| `site_lines.py` | Красноярск: `is_tracked_call()`, `branch_label()`, доб. 05/12/25 |
| `mango_vpbx.py` | Mango VPBX API (read-only) |
| `mango_sync.py` | `--site`, `--date`, `--yandex`, фильтр филиалов |
| `yandex_stt.py` | SpeechKit v3 async |
| `transcript_utils.py` | `refine_segments()` без ролей, `normalize_spoken_numbers()`, `transcript_paragraphs()` |
| `call_qc.py` | `assess_call()`, `format_day_summary(site_label=…)` |
| `telegram_format.py` | `build_call_message(..., site_label, branch)` |
| `telegram_notify.py` | `site_chat_ids(site)` — личка + группа site (legacy; звонки больше не через TG) |
| `max_notify.py` | Отправка звонков в MAX: личка + группа site |
| `send_day_to_telegram.py` | `--site moscow\|krasnoyarsk --date YYYY-MM-DD` → **MAX** |
| `daily_pipeline.py` | Multi-site loop, timer 10:00 MSK, отправка в **MAX** |
| `revenue_report.py` | Выручка: YaDisk Excel → прогноз → Telegram (личка); cron на **EU** `72.56.27.174`, 05:00 MSK |
| `tryon_usage_report.py` | Токены примерки clients vs staff → Telegram личка, 05:05 MSK |

## Деплой / утилиты

| Файл | Назначение |
|------|------------|
| `deploy/vps_install.sh` | systemd timer |
| `deploy/sync_to_vps.ps1` | scp кода на VPS |
| `deploy/send_via_vps.ps1` | send с Windows |
| `deploy/setup_new_vps.ps1` | новый VPS |
| `deploy/fix_telegram_routing.sh` | env групп TG |
| `deploy/test_mango_site.sh` | проверка API site |
| `deploy/count_tracked.sh` | звонки по филиалам |
| `deploy/vps.host` | IP VPS |
| `deploy/install_revenue_cron.sh` | cron отчётов выручки 05:00 MSK |
| `deploy/install_tryon_usage_cron.sh` | cron токенов примерки 05:05 MSK |

## Память AI

| Файл | Назначение |
|------|------------|
| `PROJECT_MEMORY.md` | Техническая база |
| `SESSION_LOG.md` | Переписка и решения |
| `CODE_MAP.md` | Этот файл |
| `AGENTS.md` | Инструкция для AI |

## Данные на VPS

```
/opt/mango-pipeline/
  calls/moscow/          # HTML Москва (legacy: корень если старые файлы)
  calls/krasnoyarsk/
  data/sent_calls_moscow.json
  data/sent_calls_krasnoyarsk.json
  data/calls_index_{site}.json
  data/yandex_cache/{site}/
  telegram_docx/{site}/
  .env                   # секреты
```

## Ключевые функции

```python
load_sites() -> List[SiteConfig]
site_chat_ids(site) -> [owner_id, group_id?]

is_tracked_call("krasnoyarsk", call) -> bool
branch_label("krasnoyarsk", call) -> "Весны (доб. 25)"

refine_segments(segs) -> [("", time, text)]  # no roles
transcript_paragraphs(transcript) -> List[str]  # DOCX lines

assess_call(transcript) -> CallAssessment  # uses full text
build_call_message(..., site_label, branch)
```

## systemd

- `mango-pipeline.timer` — 07:00 UTC = 10:00 MSK (Москва)
- `mango-pipeline.service` — `daily_pipeline.py --mango-sync --mango-days 1 --site moscow`
- `mango-pipeline-kras.timer` — **выключен 27.08.2026** (06:00 MSK); включить: `systemctl enable --now mango-pipeline-kras.timer`

## SOCO Salon — AI-примерка (отдельная задача)

| Файл | Назначение |
|------|------------|
| `docs/soco-salon-ai-tryon-session.md` | Переписка: Perfect Corp vs AILab/GPT, архитектура |
| `docs/perfectcorp-hair-tryon-cheatsheet.md` | Краткая справка YouCam hair-transfer: endpoints, units, лимиты фото |
| `tools/hair_tryon_test/run_comparison.py` | Тест API примерки |
| `tryon-web/` | **Веб YouCam**: согласие ПДн → «до» + до 2 реф (upload/портфолио) → «после» на сайте; Метрика ClientID (64069270) |
| `tryon-web/static/staff.html` + `tryon-web/static/staff.js` | Кабинет сотрудников: вход по телефону/паролю, генерация без бота, просмотр базы генераций |
| `tryon-web/app/staff_auth.py` | SQLite auth staff users, cookie-сессия, bootstrap из `.env` |
| `tryon-web/deploy/build_portfolio.py` | Скачать портфолио SOCO в `static/portfolio/` |
| `docs/SECURITY_AUDIT_2026-07-28.md` | Аудит утечек на GitHub |

---

*Обновлено: 2026-08-01*
