# Инструкции для AI-агента

1. **Первым делом прочитай (целиком):**
   - `PROJECT_MEMORY.md` — техническая база (2 города, Telegram, QC)
   - `SESSION_LOG.md` — переписка и решения по сессиям
   - `CODE_MAP.md` — карта файлов
2. На VPS те же файлы: `/opt/mango-pipeline/`
3. **Не коммить** `.env`, API keys, salts, bot tokens.
4. Telegram — **только с VPS** (`deploy/vps.host` → `72.56.27.174`).
5. Отправлять **только косячные** + сомнительные; хорошие — skip.
6. **Multi-site:** `--site moscow` или `--site krasnoyarsk`; оба в `daily_pipeline`.
7. **Telegram routing:** `site_chat_ids(site)` — Москва → личка + «Москва Фили»; Красноярск → личка + «soco красноярsk». Не использовать `TELEGRAM_EXTRA_CHAT_IDS`.
8. **Красноярск:** только доб. 05/12/25 (`site_lines.py`); Горького и «потерянные» — игнор.
9. **DOCX:** без «Администратор/Клиент», цифры цифрами (`transcript_paragraphs`).
10. Пайплайн — **только вчера** по дате в имени HTML, не весь архив.
11. Mango API — **только чтение**, настройки АТС не менять.
12. После важных изменений — обнови память и скопируй на VPS:

```powershell
scp -i $env:USERPROFILE\.ssh\id_ed25519 PROJECT_MEMORY.md SESSION_LOG.md CODE_MAP.md AGENTS.md root@72.56.27.174:/opt/mango-pipeline/
```
