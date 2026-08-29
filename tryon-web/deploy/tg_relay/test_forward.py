#!/usr/bin/env python3
"""Compare webhook secrets and POST a fake /start update to NSK via poller config."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


def env_val(path: str, key: str) -> str:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def main() -> None:
    secret = env_val("/opt/soco-tg-relay/.env", "TRYON_BOT_WEBHOOK_SECRET")
    forward = env_val("/opt/soco-tg-relay/.env", "TRYON_TG_FORWARD_URL")
    print("ams_secret_len", len(secret))
    print("forward", forward)

    # synthetic Telegram update (no session unlock expected without payload)
    update = {
        "update_id": 999999001,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 789815398, "type": "private"},
            "from": {"id": 789815398, "is_bot": False, "first_name": "Test"},
            "text": "/start",
        },
    }
    body = json.dumps(update).encode("utf-8")
    req = urllib.request.Request(
        forward,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("forward_status", resp.status)
            print("forward_body", resp.read().decode()[:300])
    except Exception as exc:
        print("forward_error", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
