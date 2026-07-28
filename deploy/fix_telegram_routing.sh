#!/bin/bash
# Одноразовая настройка маршрутизации Telegram на VPS.
# Перед запуском задайте ID групп (из getUpdates бота), не храните их в git:
#   export SITE_MOSCOW_GROUP_CHAT_IDS='-100...'
#   export SITE_KRASNOYARSK_GROUP_CHAT_IDS='-100...'
set -e
: "${SITE_MOSCOW_GROUP_CHAT_IDS:?Set SITE_MOSCOW_GROUP_CHAT_IDS}"
: "${SITE_KRASNOYARSK_GROUP_CHAT_IDS:?Set SITE_KRASNOYARSK_GROUP_CHAT_IDS}"
bash /root/set_env_var.sh /opt/mango-pipeline/.env SITE_MOSCOW_GROUP_CHAT_IDS "$SITE_MOSCOW_GROUP_CHAT_IDS"
bash /root/set_env_var.sh /opt/mango-pipeline/.env SITE_KRASNOYARSK_GROUP_CHAT_IDS "$SITE_KRASNOYARSK_GROUP_CHAT_IDS"
bash /root/set_env_var.sh /opt/mango-pipeline/.env SITE_MOSCOW_NOTIFY_OWNER 1
bash /root/set_env_var.sh /opt/mango-pipeline/.env SITE_KRASNOYARSK_NOTIFY_OWNER 1
bash /root/set_env_var.sh /opt/mango-pipeline/.env TELEGRAM_EXTRA_CHAT_IDS ''
cd /opt/mango-pipeline
.venv/bin/python - <<'PY'
import os
from pathlib import Path

def load_dotenv(path):
    for raw in Path(".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv(Path(".env"))
from site_config import load_sites
from telegram_notify import site_chat_ids

for s in load_sites():
    print(f"{s.site_id} -> {site_chat_ids(s)}")
PY
