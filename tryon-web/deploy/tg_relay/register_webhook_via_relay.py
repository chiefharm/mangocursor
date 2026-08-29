#!/usr/bin/env python3
"""Register Telegram webhook via local Amsterdam relay (EU can reach api.telegram.org)."""
from __future__ import annotations

import json
import os
import urllib.request

from dotenv import load_dotenv

load_dotenv("/opt/soco-tg-relay/.env")
load_dotenv("/opt/mango-pipeline/.env")
load_dotenv("/opt/soco-tryon/.env")

PUBLIC = os.getenv("TRYON_PUBLIC_URL", "https://primerka.soco-salon.ru").rstrip("/")
SECRET = os.getenv("TRYON_BOT_WEBHOOK_SECRET", "soco-tryon-hook").strip()
RELAY = os.getenv("TRYON_TG_RELAY_URL", "http://127.0.0.1:18100").rstrip("/")
RELAY_SECRET = os.getenv("TRYON_TG_RELAY_SECRET", "soco-tg-relay").strip()


def call(method: str, payload: dict | None = None) -> dict:
    url = f"{RELAY}/bot/{method}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={
            "X-Relay-Secret": RELAY_SECRET,
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


print("relay", RELAY)
print("public webhook", f"{PUBLIC}/api/bots/telegram")
print("getMe", call("getMe"))
print(
    "setWebhook",
    call(
        "setWebhook",
        {
            "url": f"{PUBLIC}/api/bots/telegram",
            "secret_token": SECRET,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        },
    ),
)
print("getWebhookInfo", call("getWebhookInfo"))
print("OK")
