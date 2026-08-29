"""MAX messenger helpers for try-on lead notifications."""

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
from typing import Iterable


MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")


def _tls_context() -> ssl.SSLContext:
    insecure = os.getenv("MAX_TLS_INSECURE", "1").strip().lower() in ("1", "true", "yes")
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request_json(req: urllib.request.Request, *, timeout: int = 90) -> dict:
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
        raise RuntimeError(f"MAX non-JSON: {raw[:400]}") from exc


def lead_targets() -> list[tuple[str, str]]:
    """Return [(kind, id), ...] for try-on leads."""
    targets: list[tuple[str, str]] = []
    raw = os.getenv("TRYON_MAX_CHAT_IDS", "").strip()
    if raw:
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if part.startswith("user:"):
                targets.append(("user_id", part.split(":", 1)[1]))
            else:
                targets.append(("chat_id", part.removeprefix("chat:")))
        return targets

    owner = os.getenv("MAX_OWNER_USER_ID", "").strip()
    if owner:
        targets.append(("user_id", owner))
    for key in ("MAX_KRASNOYARSK_CHAT_ID", "MAX_MOSCOW_CHAT_ID"):
        gid = os.getenv(key, "").strip()
        if gid and ("chat_id", gid) not in targets:
            targets.append(("chat_id", gid))
    return targets


def _multipart(field: str, path: Path, boundary: str) -> bytes:
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    body.extend(path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body)


def _extract_upload_token(uploaded: dict) -> str:
    """MAX image upload responses vary: token / photos.<id>.token / photos as str."""
    if not isinstance(uploaded, dict):
        return ""
    media = str(uploaded.get("token") or "").strip()
    if media:
        return media
    photos = uploaded.get("photos")
    if isinstance(photos, str) and photos.strip():
        return photos.strip()
    if isinstance(photos, dict):
        nested = str(photos.get("token") or "").strip()
        if nested:
            return nested
        for val in photos.values():
            if isinstance(val, dict):
                nested = str(val.get("token") or "").strip()
                if nested:
                    return nested
            elif isinstance(val, str) and val.strip():
                return val.strip()
    if isinstance(photos, list):
        for item in photos:
            if isinstance(item, dict):
                nested = str(item.get("token") or "").strip()
                if nested:
                    return nested
    payload = uploaded.get("payload")
    if isinstance(payload, dict):
        return str(payload.get("token") or "").strip()
    return ""


def _upload_image(token: str, path: Path) -> str:
    meta_req = urllib.request.Request(
        f"{MAX_API_BASE}/uploads?type=image",
        method="POST",
        headers={"Authorization": token},
    )
    meta = _request_json(meta_req)
    upload_url = meta.get("url")
    if not upload_url:
        raise RuntimeError(f"MAX /uploads no url: {meta}")

    boundary = f"----MaxBoundary{uuid.uuid4().hex}"
    upload_req = urllib.request.Request(
        upload_url,
        data=_multipart("data", path, boundary),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    uploaded = _request_json(upload_req, timeout=120)
    media = _extract_upload_token(uploaded)
    if not media:
        # Sometimes token is already in the init response for images
        media = _extract_upload_token(meta if isinstance(meta, dict) else {})
    if not media:
        raise RuntimeError(f"MAX image upload without token: {uploaded}")
    return media


def send_text(token: str, kind: str, value: str, text: str) -> None:
    params = urllib.parse.urlencode({kind: value})
    req = urllib.request.Request(
        f"{MAX_API_BASE}/messages?{params}",
        data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    data = _request_json(req)
    if data.get("code") or data.get("success") is False:
        raise RuntimeError(f"MAX text failed {kind}={value}: {data}")


def send_text_with_buttons(
    token: str,
    kind: str,
    value: str,
    text: str,
    rows: list[list[tuple[str, str]]],
) -> None:
    """Send text with inline callback buttons. rows = [[(label, payload), ...], ...]."""
    buttons = [
        [{"type": "callback", "text": label, "payload": payload} for label, payload in row]
        for row in rows
    ]
    params = urllib.parse.urlencode({kind: value})
    body = {
        "text": text,
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    }
    req = urllib.request.Request(
        f"{MAX_API_BASE}/messages?{params}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    data = _request_json(req)
    if data.get("code") or data.get("success") is False:
        raise RuntimeError(f"MAX buttons failed {kind}={value}: {data}")


def send_text_with_link_buttons(
    token: str,
    kind: str,
    value: str,
    text: str,
    rows: list[list[tuple[str, str]]],
) -> None:
    """Send text with link buttons. rows = [[(label, url), ...], ...]."""
    buttons = [
        [{"type": "link", "text": label, "url": url} for label, url in row]
        for row in rows
    ]
    params = urllib.parse.urlencode({kind: value})
    body = {
        "text": text,
        "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}],
    }
    req = urllib.request.Request(
        f"{MAX_API_BASE}/messages?{params}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    data = _request_json(req)
    if data.get("code") or data.get("success") is False:
        raise RuntimeError(f"MAX link buttons failed {kind}={value}: {data}")


def answer_callback(token: str, callback_id: str, *, notification: str = "") -> None:
    """Acknowledge MAX message_callback (required by platform)."""
    if not callback_id:
        return
    params = urllib.parse.urlencode({"callback_id": callback_id})
    body: dict = {}
    if notification:
        body["notification"] = notification[:200]
    req = urllib.request.Request(
        f"{MAX_API_BASE}/answers?{params}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    try:
        _request_json(req, timeout=30)
    except Exception:
        pass


def send_image(token: str, kind: str, value: str, path: Path, caption: str = "") -> None:
    media = _upload_image(token, path)
    params_q = urllib.parse.urlencode({kind: value})
    payload = {
        "text": (caption or "")[:2000],
        "attachments": [{"type": "image", "payload": {"token": media}}],
    }
    req = urllib.request.Request(
        f"{MAX_API_BASE}/messages?{params_q}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    last: Exception | None = None
    for pause in (0, 1, 2, 4, 8):
        if pause:
            time.sleep(pause)
        try:
            data = _request_json(req, timeout=120)
            if data.get("code") == "attachment.not.ready":
                last = RuntimeError(str(data))
                continue
            if data.get("code") or data.get("success") is False:
                raise RuntimeError(f"MAX image failed {kind}={value}: {data}")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"MAX image send failed: {last}")


def send_image_url(token: str, kind: str, value: str, url: str, caption: str = "") -> None:
    """Send image by public HTTPS URL (no upload token dance)."""
    params = urllib.parse.urlencode({kind: value})
    payload = {
        "text": (caption or "")[:2000],
        "attachments": [{"type": "image", "payload": {"url": url}}],
    }
    req = urllib.request.Request(
        f"{MAX_API_BASE}/messages?{params}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    data = _request_json(req, timeout=120)
    if data.get("code") or data.get("success") is False:
        raise RuntimeError(f"MAX image url failed {kind}={value}: {data}")


def send_image_smart(
    token: str,
    kind: str,
    value: str,
    path: Path,
    *,
    public_url: str = "",
    caption: str = "",
) -> None:
    """Prefer upload token; fall back to public URL if upload parsing fails."""
    try:
        send_image(token, kind, value, path, caption=caption)
        return
    except Exception as upload_exc:  # noqa: BLE001
        if not public_url:
            raise
        try:
            send_image_url(token, kind, value, public_url, caption=caption)
        except Exception as url_exc:  # noqa: BLE001
            raise RuntimeError(f"upload={upload_exc}; url={url_exc}") from url_exc


def notify_lead(
    *,
    name: str,
    phone: str,
    job_id: str,
    images: Iterable[Path],
    intent: str = "book",
    client_id: str = "",
    generation_id: str = "",
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
) -> list[str]:
    token = os.getenv("MAX_BOT_TOKEN", "").strip().strip('"')
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN is not configured")

    targets = lead_targets()
    if not targets:
        raise RuntimeError("No MAX chat targets (set TRYON_MAX_CHAT_IDS or MAX_*_CHAT_ID)")

    public_base = os.getenv("TRYON_PUBLIC_URL", "https://primerka.soco-salon.ru").rstrip("/")
    intent_label = "расчёт стоимости" if intent == "quote" else "запись к стилисту"
    text = (
        f"AI-примерка SOCO — {intent_label}\n"
        f"client_id: {client_id or '—'}\n"
        f"generation_id: {generation_id or '—'}\n"
        f"ym_cid: {ym_cid or '—'}\n"
        f"yclid: {yclid or '—'}\n"
        f"utm: {utm_source or '—'}/{utm_medium or '—'}/{utm_campaign or '—'}\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"job: {job_id}"
    )
    errors: list[str] = []
    paths = [p for p in images if p.exists()]
    for kind, value in targets:
        try:
            send_text(token, kind, value, text)
            time.sleep(0.6)
            for path in paths:
                label = path.stem
                # uploads/… or results/…
                rel = "results" if "results" in str(path).replace("\\", "/") else "uploads"
                pub = f"{public_base}/api/{rel}/{job_id}/{path.name}"
                send_image_smart(token, kind, value, path, public_url=pub, caption=label)
                time.sleep(0.6)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{kind}={value}: {exc}")
    return errors
