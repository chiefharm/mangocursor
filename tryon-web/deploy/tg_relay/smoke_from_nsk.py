#!/usr/bin/env python3
"""Smoke: NSK -> Amsterdam TG relay getMe (+ optional sendMessage)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

env: dict[str, str] = {}
for line in Path("/opt/soco-tryon/.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

relay = env.get("TRYON_TG_RELAY_URL", "").rstrip("/")
secret = env.get("TRYON_TG_RELAY_SECRET", "soco-tg-relay")
if not relay:
    print("FAIL: TRYON_TG_RELAY_URL missing")
    sys.exit(1)

req = urllib.request.Request(
    f"{relay}/bot/getMe",
    headers={"X-Relay-Secret": secret},
    method="GET",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode("utf-8"))
print("getMe", data)
if not data.get("ok"):
    sys.exit(2)

chat = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
if chat:
    body = json.dumps(
        {"chat_id": chat, "text": "SOCO TG relay OK (Amsterdam → Telegram)"},
        ensure_ascii=False,
    ).encode("utf-8")
    req2 = urllib.request.Request(
        f"{relay}/bot/sendMessage",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Relay-Secret": secret},
    )
    with urllib.request.urlopen(req2, timeout=30) as resp:
        print("sendMessage", resp.read().decode("utf-8"))

print("OK")
