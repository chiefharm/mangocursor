"""Telegram send helpers — one or many chat IDs."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import List


def parse_chat_ids(
    primary: str | None = None,
    extra: str | None = None,
    *,
    group_ids: List[str] | None = None,
) -> List[str]:
    """TELEGRAM_CHAT_ID (owner) + optional group/extra chat IDs."""
    if primary is None:
        primary = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if extra is None:
        extra = os.getenv("TELEGRAM_EXTRA_CHAT_IDS", "").strip()

    ids: List[str] = []
    for raw in (primary,):
        if raw and raw not in ids:
            ids.append(raw)
    for source in (group_ids or [], _chat_id_list(extra)):
        for part in source:
            if part and part not in ids:
                ids.append(part)
    return ids


def _chat_id_list(raw: str) -> List[str]:
    ids: List[str] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part and part not in ids:
            ids.append(part)
    return ids


def site_chat_ids(site) -> List[str]:
    """Owner (TELEGRAM_CHAT_ID) + site-specific group only."""
    prefix = f"SITE_{site.site_id.upper()}_"
    notify_owner = os.getenv(f"{prefix}NOTIFY_OWNER", "1").strip().lower()

    ids: List[str] = []
    if notify_owner in ("1", "true", "yes"):
        primary = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if primary:
            ids.append(primary)
    for gid in site.group_chat_ids:
        if gid and gid not in ids:
            ids.append(gid)
    return ids


def tg_send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    timeout: int = 60,
    parse_mode: str | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    fields = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        fields["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        migrated = _migrated_chat_id(detail)
        if migrated and migrated != chat_id:
            print(f"[INFO] Telegram chat migrated {chat_id} -> {migrated}")
            tg_send_message(
                token, migrated, text, timeout=timeout, parse_mode=parse_mode
            )
            return
        raise RuntimeError(f"sendMessage to {chat_id} HTTP {exc.code}: {detail}") from exc
    if '"ok":true' not in body:
        raise RuntimeError(f"sendMessage to {chat_id} failed: {body}")


def _migrated_chat_id(error_body: str) -> str:
    try:
        data = json.loads(error_body)
    except json.JSONDecodeError:
        return ""
    params = data.get("parameters") or {}
    migrated = params.get("migrate_to_chat_id")
    return str(migrated) if migrated else ""


def tg_send_document(
    token: str, chat_id: str, file_path: Path, caption: str, *, timeout: int = 120
) -> None:
    boundary = f"----MangoBoundary{uuid.uuid4().hex}"
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    file_bytes = file_path.read_bytes()

    def part_text(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = bytearray()
    body.extend(part_text("chat_id", chat_id))
    body.extend(part_text("caption", caption[:1024]))
    body.extend(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{file_path.name}"\r\n'
            "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        migrated = _migrated_chat_id(detail)
        if migrated and migrated != chat_id:
            print(f"[INFO] Telegram chat migrated {chat_id} -> {migrated}")
            tg_send_document(token, migrated, file_path, caption, timeout=timeout)
            return
        raise RuntimeError(f"sendDocument to {chat_id} HTTP {exc.code}: {detail}") from exc
    if '"ok":true' not in body_text:
        raise RuntimeError(f"sendDocument to {chat_id} failed: {body_text}")


def tg_broadcast_message(
    token: str,
    chat_ids: List[str],
    text: str,
    *,
    parse_mode: str | None = None,
) -> None:
    for chat_id in chat_ids:
        try:
            tg_send_message(token, chat_id, text, parse_mode=parse_mode)
        except Exception as exc:
            print(f"[WARN] Telegram message to {chat_id}: {exc}")


def tg_broadcast_document(
    token: str, chat_ids: List[str], file_path: Path, caption: str
) -> None:
    for chat_id in chat_ids:
        try:
            tg_send_document(token, chat_id, file_path, caption)
        except Exception as exc:
            print(f"[WARN] Telegram document to {chat_id}: {exc}")
