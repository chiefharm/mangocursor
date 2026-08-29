#!/usr/bin/env python3
"""Long-poll Telegram updates on Amsterdam and forward to NSK tryon webhook.

Telegram often cannot reliably POST webhooks into RU. Outbound Bot API already
goes through soco-tg-relay; this poller closes the inbound gap without needing
HTTPS on Amsterdam.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv("/opt/soco-tg-relay/.env")
load_dotenv("/opt/mango-pipeline/.env")

RELAY = os.getenv("TRYON_TG_RELAY_URL", "http://127.0.0.1:18100").rstrip("/")
RELAY_SECRET = os.getenv("TRYON_TG_RELAY_SECRET", "soco-tg-relay").strip()
FORWARD_URL = os.getenv(
    "TRYON_TG_FORWARD_URL",
    "https://primerka.soco-salon.ru/api/bots/telegram",
).strip()
WEBHOOK_SECRET = os.getenv("TRYON_BOT_WEBHOOK_SECRET", "soco-tryon-hook").strip()
OFFSET_FILE = os.getenv("TRYON_TG_OFFSET_FILE", "/opt/soco-tg-relay/data/offset.txt")


def relay_call(method: str, payload: dict | None = None, *, timeout: int = 60) -> dict:
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def forward(update: dict) -> None:
    body = json.dumps(update, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        FORWARD_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET,
        },
    )
    # NSK may have flaky TLS; allow retries
    last: Exception | None = None
    for pause in (0, 1, 2, 4):
        if pause:
            time.sleep(pause)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"forward failed: {last}")


def load_offset() -> int:
    try:
        return int(Path_read())
    except Exception:
        return 0


def Path_read() -> str:
    from pathlib import Path

    p = Path(OFFSET_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        return "0"
    return p.read_text(encoding="utf-8").strip() or "0"


def save_offset(value: int) -> None:
    from pathlib import Path

    p = Path(OFFSET_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(value), encoding="utf-8")


def main() -> None:
    print("forward_url", FORWARD_URL, flush=True)
    # Stop broken RU webhook so getUpdates works
    try:
        print("deleteWebhook", relay_call("deleteWebhook", {"drop_pending_updates": False}), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("deleteWebhook_warn", exc, flush=True)

    offset = load_offset()
    print("start_offset", offset, flush=True)
    while True:
        try:
            data = relay_call(
                "getUpdates",
                {"timeout": 25, "offset": offset, "allowed_updates": ["message", "callback_query"]},
                timeout=60,
            )
            if not data.get("ok"):
                print("getUpdates_bad", data, flush=True)
                time.sleep(3)
                continue
            updates = data.get("result") or []
            if not updates:
                continue
            for upd in updates:
                upd_id = int(upd.get("update_id") or 0)
                try:
                    forward(upd)
                    print("forwarded", upd_id, flush=True)
                except Exception as exc:  # noqa: BLE001
                    print("forward_error", upd_id, exc, flush=True)
                offset = upd_id + 1
                save_offset(offset)
        except urllib.error.URLError as exc:
            print("poll_error", exc, flush=True)
            time.sleep(3)
        except Exception as exc:  # noqa: BLE001
            print("loop_error", exc, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
