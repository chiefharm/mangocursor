"""Email delivery for try-on leads."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable


def lead_email_to() -> str:
    return os.getenv("LEAD_EMAIL_TO", "p9050874245@gmail.com").strip()


def send_lead_email(
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
) -> None:
    to_addr = lead_email_to()
    if not to_addr:
        raise RuntimeError("LEAD_EMAIL_TO is empty")

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or "587")
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", user or to_addr).strip()

    if not host or not user or not password:
        raise RuntimeError(
            "SMTP not configured (need SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env)"
        )

    intent_label = "расчёт стоимости" if intent == "quote" else "запись к стилисту"
    msg = EmailMessage()
    msg["Subject"] = f"SOCO AI-примерка ({intent_label}): {client_id or name}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(
        "Заявка с AI-примерки SOCO\n\n"
        f"Тип: {intent_label}\n"
        f"client_id: {client_id or '—'}\n"
        f"generation_id: {generation_id or '—'}\n"
        f"ym_cid: {ym_cid or '—'}\n"
        f"yclid: {yclid or '—'}\n"
        f"utm_source: {utm_source or '—'}\n"
        f"utm_medium: {utm_medium or '—'}\n"
        f"utm_campaign: {utm_campaign or '—'}\n"
        f"utm_content: {utm_content or '—'}\n"
        f"utm_term: {utm_term or '—'}\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"job_id: {job_id}\n\n"
        "Во вложении: фото «до» и «после».\n"
    )

    for path in images:
        if not path.exists():
            continue
        data = path.read_bytes()
        maintype, subtype = "image", "jpeg"
        if path.suffix.lower() == ".png":
            subtype = "png"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

    with smtplib.SMTP(host, port, timeout=60) as smtp:
        smtp.ehlo()
        if os.getenv("SMTP_STARTTLS", "1").strip() not in ("0", "false", "no"):
            smtp.starttls()
            smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)
