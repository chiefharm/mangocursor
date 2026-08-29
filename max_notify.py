"""MAX messenger send helpers (text + file attachments)."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import List, Tuple


MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")


def _chat_id_list(raw: str) -> List[str]:
    ids: List[str] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part and part not in ids:
            ids.append(part)
    return ids


def _tls_context() -> ssl.SSLContext:
    # VPS currently may miss trusted roots for MAX; allow opt-out with MAX_TLS_INSECURE=0.
    insecure = os.getenv("MAX_TLS_INSECURE", "1").strip().lower() in ("1", "true", "yes")
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _max_targets_for_site(site) -> List[Tuple[str, str]]:
    prefix = f"SITE_{site.site_id.upper()}_"
    notify_owner = os.getenv(f"{prefix}NOTIFY_OWNER", "1").strip().lower()

    targets: List[Tuple[str, str]] = []
    if notify_owner in ("1", "true", "yes"):
        owner_user = os.getenv("MAX_OWNER_USER_ID", "").strip()
        owner_chat = os.getenv("MAX_OWNER_CHAT_ID", "").strip()
        if owner_user:
            targets.append(("user_id", owner_user))
        elif owner_chat:
            targets.append(("chat_id", owner_chat))

    site_var = f"MAX_{site.site_id.upper()}_CHAT_ID"
    for gid in _chat_id_list(os.getenv(site_var, "").strip()):
        if gid and ("chat_id", gid) not in targets:
            targets.append(("chat_id", gid))
    return targets


def max_site_chat_ids(site) -> List[str]:
    """Compatibility helper for quick checks in scripts/tests."""
    return [f"{kind}:{value}" for kind, value in _max_targets_for_site(site)]


def max_revenue_targets(city: str) -> List[Tuple[str, str]]:
    city = city.strip().lower()
    targets: List[Tuple[str, str]] = []
    owner_user = os.getenv("MAX_OWNER_USER_ID", "").strip()
    owner_chat = os.getenv("MAX_OWNER_CHAT_ID", "").strip()
    if owner_user:
        targets.append(("user_id", owner_user))
    elif owner_chat:
        targets.append(("chat_id", owner_chat))

    if "крас" in city:
        var = "MAX_KRASNOYARSK_CHAT_ID"
    else:
        var = "MAX_MOSCOW_CHAT_ID"
    for gid in _chat_id_list(os.getenv(var, "").strip()):
        if gid and ("chat_id", gid) not in targets:
            targets.append(("chat_id", gid))
    return targets


def _request_json(req: urllib.request.Request, *, timeout: int = 60) -> dict:
    try:
        with urllib.request.urlopen(req, context=_tls_context(), timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MAX HTTP {exc.code}: {detail}") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MAX API non-JSON response: {raw[:500]}") from exc


def _clean_max_text(text: str) -> str:
    # Telegram HTML tags are not MAX format; strip wrappers but keep content.
    return (
        text.replace("<b>", "")
        .replace("</b>", "")
        .replace('<span class="tg-spoiler">', "")
        .replace("</span>", "")
    )


def max_send_message(
    token: str,
    target_kind: str,
    target_value: str,
    text: str,
    *,
    timeout: int = 60,
) -> None:
    params = urllib.parse.urlencode({target_kind: target_value})
    url = f"{MAX_API_BASE}/messages?{params}"
    payload = json.dumps({"text": _clean_max_text(text)}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    data = _request_json(req, timeout=timeout)
    if data.get("code") or data.get("success") is False:
        raise RuntimeError(f"MAX send message failed for {target_kind}={target_value}: {data}")


def _multipart_bytes(field_name: str, file_path: Path, boundary: str) -> bytes:
    data = bytearray()
    data.extend(f"--{boundary}\r\n".encode("utf-8"))
    data.extend(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
    )
    data.extend(file_path.read_bytes())
    data.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return bytes(data)


def _max_upload_file(token: str, file_path: Path) -> str:
    req = urllib.request.Request(
        f"{MAX_API_BASE}/uploads?type=file",
        method="POST",
        headers={"Authorization": token},
    )
    meta = _request_json(req, timeout=60)
    upload_url = meta.get("url")
    if not upload_url:
        raise RuntimeError(f"MAX /uploads returned no url: {meta}")

    boundary = f"----MaxBoundary{uuid.uuid4().hex}"
    body = _multipart_bytes("data", file_path, boundary)
    upload_req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    upload_resp = _request_json(upload_req, timeout=120)
    token_value = str(upload_resp.get("token", "")).strip()
    if not token_value:
        raise RuntimeError(f"MAX upload did not return token: {upload_resp}")
    return token_value


def max_send_document(
    token: str,
    target_kind: str,
    target_value: str,
    file_path: Path,
    caption: str = "",
) -> None:
    media_token = _max_upload_file(token, file_path)
    params = urllib.parse.urlencode({target_kind: target_value})
    url = f"{MAX_API_BASE}/messages?{params}"
    payload = {
        "text": _clean_max_text(caption)[:2000],
        "attachments": [{"type": "file", "payload": {"token": media_token}}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    waits = (1, 2, 4, 8)
    last_error: RuntimeError | None = None
    for idx, pause in enumerate((0, *waits)):
        if pause:
            time.sleep(pause)
        try:
            data = _request_json(req, timeout=120)
            if data.get("code") or data.get("success") is False:
                raise RuntimeError(
                    f"MAX send file failed for {target_kind}={target_value}: {data}"
                )
            return
        except RuntimeError as exc:
            last_error = exc
            text = str(exc)
            retryable = "attachment.not.ready" in text or "MAX HTTP 400" in text
            if retryable and idx < len(waits):
                continue
            raise
    if last_error is not None:
        raise last_error


def max_broadcast_message(token: str, targets: List[Tuple[str, str]], text: str) -> None:
    for kind, value in targets:
        try:
            max_send_message(token, kind, value, text)
        except Exception as exc:
            print(f"[WARN] MAX message to {kind}={value}: {exc}")


def max_broadcast_document(
    token: str,
    targets: List[Tuple[str, str]],
    file_path: Path,
    caption: str = "",
) -> None:
    for kind, value in targets:
        try:
            max_send_document(token, kind, value, file_path, caption=caption)
        except Exception as exc:
            print(f"[WARN] MAX document to {kind}={value}: {exc}")
