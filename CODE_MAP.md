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
| `telegram_notify.py` | `site_chat_ids(site)` — личка + группа site |
| `send_day_to_telegram.py` | `--site moscow\|krasnoyarsk --date YYYY-MM-DD` |
| `daily_pipeline.py` | Multi-site loop, timer 10:00 MSK |
| `revenue_report.py` | Выручка: YaDisk Excel → прогноз → Telegram (личка), 05:00 MSK |

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

- `mango-pipeline.timer` — 07:00 UTC = 10:00 MSK
- `mango-pipeline.service` — `daily_pipeline.py --mango-sync --mango-days 1`

## SOCO Salon — AI-примерка (отдельная задача)

| Файл | Назначение |
|------|------------|
| `docs/soco-salon-ai-tryon-session.md` | Переписка: Perfect Corp vs AILab/GPT, архитектура |
| `tools/hair_tryon_test/run_comparison.py` | Тест API примерки |
| `tryon-web/` | **Веб-сервис YouCam**: «до» + до 3 референсов → «после» |
| `personal-finance/` | **Отдельный** личный учёт: выписка → сайт → пояснение переводов. Группа Telegram: итоги, цель, всплески, кнопки обратной связи. Не салон/Mango |
| `docs/SECURITY_AUDIT_2026-07-28.md` | Аудит утечек на GitHub |

---

*Обновлено: 2026-08-29*
