# Автоматическая отправка расшифровок с VPS

Скрипт `daily_pipeline.py` работает на сервере 24/7 и каждый день:
1. Берет новые HTML-расшифровки звонков.
2. Автоматически отбирает проблемные.
3. Делает DOCX (удобно на iPhone).
4. Отправляет в Telegram: сначала короткий комментарий, потом файл.

## Быстрый деплой на VPS

```bash
ssh root@72.56.249.113
curl -fsSL https://raw.githubusercontent.com/chiefharm/mangocursor/master/deploy/vps_install.sh -o /root/vps_install.sh
bash /root/vps_install.sh
nano /opt/mango-pipeline/.env
```

В `.env`:
```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Тест:
```bash
/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --dry-run
```

Реальный запуск:
```bash
systemctl start mango-pipeline.service
```

## Как попадают новые звонки на сервер

Вариант A (простой): выгружаете HTML из Mango и кладете в репозиторий `mangocursor`, затем на VPS срабатывает `git pull` по расписанию.

Вариант B: загружаете HTML на сервер в `/opt/mango-pipeline/incoming` и запускаете:
```bash
/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --calls-dir /opt/mango-pipeline/incoming
```

## Расписание

По умолчанию: каждый день в 20:00 МСК (`17:00 UTC`).

Проверить таймер:
```bash
systemctl status mango-pipeline.timer
```
