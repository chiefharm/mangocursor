#!/usr/bin/env python3
"""Print Telegram chat IDs from recent bot updates (for group setup)."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    base = Path(__file__).resolve().parent
    load_dotenv(base / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env")

    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=50"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if not data.get("ok"):
        raise SystemExit(f"getUpdates failed: {data}")

    seen: set[int] = set()
    print("Чаты, где бот недавно получал сообщения:\n")
    for item in data.get("result", []):
        msg = item.get("message") or item.get("my_chat_member", {}).get("chat") or {}
        if isinstance(msg, dict) and "chat" in msg:
            chat = msg["chat"]
        elif isinstance(msg, dict):
            chat = msg
        else:
            continue
        cid = chat.get("id")
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        title = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
        ctype = chat.get("type", "?")
        print(f"  id={cid}")
        print(f"    тип: {ctype}, название: {title}")
        if str(cid).startswith("-"):
            print(f"    → для группы в .env: TELEGRAM_EXTRA_CHAT_IDS={cid}")
        else:
            print(f"    → личный чат (TELEGRAM_CHAT_ID)")
        print()

    if not seen:
        print(
            "Пусто. Напишите что-нибудь в группе с ботом (или /start), "
            "затем запустите скрипт снова."
        )


if __name__ == "__main__":
    main()
