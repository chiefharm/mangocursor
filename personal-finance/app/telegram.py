"""Telegram Bot API helpers. Optional — the site works without it."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def telegram_enabled() -> bool:
    flag = os.getenv("FINANCE_TELEGRAM_ENABLED", "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("FINANCE_TELEGRAM_BOT_TOKEN") and os.getenv("FINANCE_TELEGRAM_CHAT_ID"))


def token() -> str:
    return os.getenv("FINANCE_TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> str:
    return os.getenv("FINANCE_TELEGRAM_CHAT_ID", "").strip()


def allowed_chat(raw: Any) -> bool:
    want = chat_id()
    if not want:
        return False
    return str(raw) == want


def site_url() -> str:
    return os.getenv("FINANCE_SITE_URL", "").strip()


def api(method: str, payload: dict[str, Any] | None = None, *, timeout: int = 35) -> dict[str, Any]:
    tok = token()
    if not tok:
        raise RuntimeError("FINANCE_TELEGRAM_BOT_TOKEN не задан")
    url = f"https://api.telegram.org/bot{tok}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram {method} HTTP {exc.code}: {detail}") from exc
    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body}")
    return parsed


def send_message(
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: dict[str, Any] | None = None,
    chat: str | None = None,
) -> dict[str, Any]:
    dest = chat or chat_id()
    if not dest:
        raise RuntimeError("Telegram не настроен (FINANCE_TELEGRAM_CHAT_ID)")
    payload: dict[str, Any] = {
        "chat_id": dest,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return api("sendMessage", payload)


def answer_callback(callback_id: str, text: str, *, alert: bool = False) -> None:
    api(
        "answerCallbackQuery",
        {"callback_query_id": callback_id, "text": text[:180], "show_alert": alert},
    )


def get_updates(offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    result = api("getUpdates", payload, timeout=timeout + 10)
    updates = result.get("result") or []
    return updates if isinstance(updates, list) else []
