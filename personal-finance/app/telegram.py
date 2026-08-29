"""Send a personal finance digest to Telegram. Optional — site works without it."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def telegram_enabled() -> bool:
    flag = os.getenv("FINANCE_TELEGRAM_ENABLED", "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("FINANCE_TELEGRAM_BOT_TOKEN") and os.getenv("FINANCE_TELEGRAM_CHAT_ID"))


def send_message(text: str, *, parse_mode: str = "HTML") -> None:
    token = os.getenv("FINANCE_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("FINANCE_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram не настроен (FINANCE_TELEGRAM_BOT_TOKEN / CHAT_ID)")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from exc
    data = json.loads(body)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram send failed: {body}")
