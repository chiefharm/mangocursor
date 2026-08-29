#!/usr/bin/env python3
"""Rebuild /opt/soco-tg-relay/.env as clean UTF-8 (no BOM/CRLF/binary junk)."""
from __future__ import annotations

import re
from pathlib import Path

RELAY_ENV = Path("/opt/soco-tg-relay/.env")
MANGO_ENV = Path("/opt/mango-pipeline/.env")
NSK_SECRET_FILE = Path("/tmp/nsk_webhook_secret.txt")


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    raw = path.read_bytes()
    # strip UTF-16/UTF-8 BOM if present
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16", errors="ignore")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip().strip("\x00")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and all(32 <= ord(c) < 127 or c.isalpha() for c in k):
            out[k] = v
    return out


def main() -> None:
    mango = parse_env(MANGO_ENV)
    old = parse_env(RELAY_ENV)

    secret = ""
    if NSK_SECRET_FILE.exists():
        secret = NSK_SECRET_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        if secret.startswith("TRYON_BOT_WEBHOOK_SECRET="):
            secret = secret.split("=", 1)[1].strip().strip('"')
    if not secret:
        secret = old.get("TRYON_BOT_WEBHOOK_SECRET") or "soco-tryon-hook"

    token = (
        old.get("TELEGRAM_BOT_TOKEN")
        or old.get("TRYON_TELEGRAM_BOT_TOKEN")
        or mango.get("TELEGRAM_BOT_TOKEN")
        or mango.get("TRYON_TELEGRAM_BOT_TOKEN")
        or ""
    )
    relay_secret = old.get("TRYON_TG_RELAY_SECRET") or "soco-tg-relay"
    forward = old.get("TRYON_TG_FORWARD_URL") or "https://primerka.soco-salon.ru/api/bots/telegram"

    lines = [
        f"TRYON_TG_RELAY_SECRET={relay_secret}",
        f"TELEGRAM_BOT_TOKEN={token}",
        f"TRYON_BOT_WEBHOOK_SECRET={secret}",
        f"TRYON_TG_FORWARD_URL={forward}",
        "TRYON_TG_RELAY_URL=http://127.0.0.1:18100",
    ]
    text = "\n".join(lines) + "\n"
    RELAY_ENV.write_text(text, encoding="utf-8", newline="\n")
    print("wrote", RELAY_ENV, "bytes", RELAY_ENV.stat().st_size)
    print("keys", [l.split("=", 1)[0] for l in lines])
    print("webhook_secret_len", len(secret))
    print("token_len", len(token))


if __name__ == "__main__":
    main()
