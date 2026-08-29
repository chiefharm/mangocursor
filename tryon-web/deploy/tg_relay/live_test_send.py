#!/usr/bin/env python3
"""Live TG test from NSK via Amsterdam relay."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


def load_env(*paths: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    env = load_env("/opt/soco-tryon/.env", "/opt/mango-pipeline/.env")
    relay = (env.get("TRYON_TG_RELAY_URL") or "").rstrip("/")
    secret = env.get("TRYON_TG_RELAY_SECRET", "soco-tg-relay")
    chat = (sys.argv[1] if len(sys.argv) > 1 else env.get("TELEGRAM_CHAT_ID", "")).strip()
    if not relay:
        print("FAIL no TRYON_TG_RELAY_URL")
        return 1
    if not chat:
        print("FAIL no TELEGRAM_CHAT_ID")
        return 1

    def call(method: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{relay}/bot/{method}",
            data=data,
            method="POST" if payload is not None else "GET",
            headers={
                "X-Relay-Secret": secret,
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))

    me = call("getMe")
    print("getMe", me)
    if not me.get("ok"):
        return 2

    sent = call(
        "sendMessage",
        {
            "chat_id": chat,
            "text": (
                "SOCO test: Telegram через Amsterdam OK ✅\n"
                "Если это сообщение пришло — исходящий relay работает."
            ),
        },
    )
    print("sendMessage", sent)
    return 0 if sent.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
