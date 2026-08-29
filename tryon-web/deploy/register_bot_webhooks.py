#!/usr/bin/env python3
"""Register Telegram + MAX webhooks for try-on bot linking."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/soco-tryon")
os.chdir("/opt/soco-tryon")

from dotenv import load_dotenv

load_dotenv("/opt/soco-tryon/.env")
load_dotenv("/opt/mango-pipeline/.env")

from app.bot_delivery import set_max_webhook, set_telegram_webhook

PUBLIC = os.getenv("TRYON_PUBLIC_URL", "https://primerka.soco-salon.ru").rstrip("/")
SECRET = os.getenv("TRYON_BOT_WEBHOOK_SECRET", "soco-tryon-hook").strip()

print("public", PUBLIC)
print("TG", set_telegram_webhook(PUBLIC, SECRET))
try:
    print("MAX", set_max_webhook(PUBLIC, SECRET))
except Exception as exc:
    print("MAX_FAIL", exc)
    sys.exit(1)
print("OK")
