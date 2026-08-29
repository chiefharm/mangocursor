"""Send try-on results to the linked MAX / Telegram user."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from . import max_client

MSG_PROCESSING = "Супер, вы активировали бота. В течение 3 минут пришлем результаты примерки."
BTN_RETURN_SITE = "Вернуться пока на сайт"
MSG_STYLIST_CTA = "Желаете обсудить с нашим стилистом и получить расчет стоимости?"
MSG_CITY = "Выберите ваш город"
MSG_THANKS_NO = (
    'Если передумаете, то нажмите кнопку «Да хочу». '
    'К сожалению текстовые сообщения от вас я прочитать не смогу('
)
MSG_MASTER_HELP = "Нужна помощь в подборе мастера?"
MSG_RESULT_NOTE = (
    "Результат примерки не учитывает структуру и исходный цвет волос. "
    "Для точной реализации нужна консультация мастера SOCO. "
    "На консультации количество примерок не ограничено."
)

BTN_YES = "Да хочу"
BTN_NO = "Пока нет"
BTN_MSK = "Москва"
BTN_KRSK = "Красноярск"
BTN_PICK_MASTER = "Да, подобрать мастера"
BTN_KNOW_MASTER = "Знаю мастера, запишусь самостоятельно"

# city -> (marquiz, taplink)
CITY_BOOKING_URLS = {
    "moscow": (
        "https://mrqz.me/6a32cb2ef8f81d00199756d7",
        "https://soco-moscow.ru/taplink",
    ),
    "krasnoyarsk": (
        "https://mrqz.me/6a2bb00a0b0b620019381f83",
        "https://soco-kras.ru/taplink2gisloyality",
    ),
}

# Красноярск: разные taplink-страницы на одном счётчике Метрики
KRAS_TAPLINK_BY_HOST = {
    "soco-kras.ru": "https://soco-kras.ru/taplink2gisloyality",
    "www.soco-kras.ru": "https://soco-kras.ru/taplink2gisloyality",
    "soco-salon.ru": "https://soco-salon.ru/taplink",
    "www.soco-salon.ru": "https://soco-salon.ru/taplink",
}

CB_WANT = "want"
CB_NO = "no"
CB_MSK = "city:moscow"
CB_KRSK = "city:krasnoyarsk"


def _allowed_return_hosts() -> tuple[str, ...]:
    raw = os.getenv(
        "TRYON_RETURN_SITE_HOSTS",
        "soco-moscow.ru,soco-salon.ru,soco-kras.ru,primerka.soco-salon.ru",
    )
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def normalize_return_url(raw: str) -> str:
    """Keep only https URLs on configured SOCO salon hosts."""
    url = (raw or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    allowed = _allowed_return_hosts()
    if not any(host == h or host.endswith("." + h) for h in allowed):
        return ""
    scheme = parts.scheme if parts.scheme in {"http", "https"} else "https"
    path = parts.path or "/"
    return urllib.parse.urlunsplit((scheme, parts.netloc, path, parts.query, parts.fragment))


def return_site_keyboard(
    return_url: str,
    *,
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> list[list[tuple[str, str]]] | None:
    url = normalize_return_url(return_url)
    if not url:
        return None
    url = booking_url_with_analytics(
        url,
        ym_cid=ym_cid,
        yclid=yclid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    return [[(BTN_RETURN_SITE, url)]]


def send_processing_notice(
    *,
    channel: str,
    bot_user_id: str,
    bot_chat_id: str,
    return_url: str = "",
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> None:
    rows = return_site_keyboard(
        return_url,
        ym_cid=ym_cid,
        yclid=yclid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    if channel == "telegram":
        markup = _tg_link_keyboard(rows) if rows else None
        tg_send_text(bot_chat_id or bot_user_id, MSG_PROCESSING, reply_markup=markup)
        return
    token = max_bot_token()
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN not configured")
    if rows:
        max_client.send_text_with_link_buttons(token, "user_id", str(bot_user_id), MSG_PROCESSING, rows)
    else:
        max_client.send_text(token, "user_id", str(bot_user_id), MSG_PROCESSING)


def booking_url_with_analytics(
    base_url: str,
    *,
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> str:
    """Append Metrika ClientID (ym_cid) + UTM/yclid for cross-site analytics."""
    url = (base_url or "").strip()
    if not url:
        return url
    params: list[tuple[str, str]] = []
    yid = (ym_cid or "").strip()[:64]
    if yid:
        params.append(("ym_cid", yid))
    for key, value in (
        ("yclid", yclid),
        ("utm_source", utm_source),
        ("utm_medium", utm_medium),
        ("utm_campaign", utm_campaign),
        ("utm_content", utm_content),
        ("utm_term", utm_term),
    ):
        v = (value or "").strip()[:255]
        if v:
            params.append((key, v))
    if not params:
        return url
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    existing = {k for k, _ in q}
    for k, v in params:
        if k not in existing:
            q.append((k, v))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), parts.fragment))


def city_booking_urls(
    city: str,
    *,
    return_url: str = "",
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> tuple[str, str]:
    marquiz, taplink = CITY_BOOKING_URLS.get(city) or CITY_BOOKING_URLS["krasnoyarsk"]
    if city == "krasnoyarsk":
        host = (urllib.parse.urlsplit(normalize_return_url(return_url)).hostname or "").lower()
        taplink = KRAS_TAPLINK_BY_HOST.get(host) or taplink
    kw = dict(
        ym_cid=ym_cid,
        yclid=yclid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    return (
        booking_url_with_analytics(marquiz, **kw),
        booking_url_with_analytics(taplink, **kw),
    )


def telegram_bot_token() -> str:
    return (
        os.getenv("TRYON_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )


def tg_relay_url() -> str:
    """Amsterdam relay base URL when NSK cannot reach api.telegram.org."""
    return os.getenv("TRYON_TG_RELAY_URL", "").strip().rstrip("/")


def _tg_endpoint(method: str) -> str:
    relay = tg_relay_url()
    if relay:
        return f"{relay}/bot/{method}"
    token = telegram_bot_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
    return f"https://api.telegram.org/bot{token}/{method}"


def _tg_headers(*, content_type: str | None = "application/json") -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    if tg_relay_url():
        secret = os.getenv("TRYON_TG_RELAY_SECRET", "").strip() or "soco-tg-relay"
        headers["X-Relay-Secret"] = secret
    return headers


def _tg_require_configured() -> None:
    if tg_relay_url():
        return
    if not telegram_bot_token():
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")


def max_bot_token() -> str:
    return (
        os.getenv("TRYON_MAX_BOT_TOKEN", "").strip().strip('"')
        or os.getenv("MAX_BOT_TOKEN", "").strip().strip('"')
    )


def telegram_bot_username() -> str:
    return os.getenv("TRYON_TELEGRAM_BOT_USERNAME", "chiefharmcursorbot").strip().lstrip("@")


def max_bot_username() -> str:
    return os.getenv("TRYON_MAX_BOT_USERNAME", "id246109422108_bot").strip().lstrip("@")


def deep_link(channel: str, token: str) -> str:
    if channel == "telegram":
        return f"https://t.me/{telegram_bot_username()}?start={token}"
    return f"https://max.ru/{max_bot_username()}?start={token}"


def cb_payload(action: str, session_token: str) -> str:
    return f"{action}|{session_token}"


def parse_cb_payload(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if "|" not in raw:
        return raw, ""
    action, token = raw.split("|", 1)
    return action.strip(), token.strip()


def _tg_inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in rows
        ]
    }


def _tg_link_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "url": url} for label, url in row] for row in rows
        ]
    }


def tg_send_text(chat_id: str, text: str, *, reply_markup: dict | None = None) -> None:
    _tg_require_configured()
    url = _tg_endpoint("sendMessage")
    body: dict = {"chat_id": chat_id, "text": text}
    if reply_markup:
        body["reply_markup"] = reply_markup
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers=_tg_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"TG sendMessage failed: {data}")


def tg_answer_callback(callback_query_id: str, text: str = "") -> None:
    if not tg_relay_url() and not telegram_bot_token():
        return
    url = _tg_endpoint("answerCallbackQuery")
    body = {"callback_query_id": callback_query_id}
    if text:
        body["text"] = text[:200]
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=_tg_headers(),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def tg_send_photo(chat_id: str, path: Path, caption: str = "") -> None:
    _tg_require_configured()
    boundary = f"----Tg{os.urandom(8).hex()}"
    body = bytearray()
    fields = {"chat_id": str(chat_id), "caption": caption[:1024]}
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    data = path.read_bytes()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n".encode()
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    url = _tg_endpoint("sendPhoto")
    headers = _tg_headers(content_type=f"multipart/form-data; boundary={boundary}")
    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not out.get("ok"):
        raise RuntimeError(f"TG sendPhoto failed: {out}")


def stylist_cta_keyboard(session_token: str) -> list[list[tuple[str, str]]]:
    return [[(BTN_YES, cb_payload(CB_WANT, session_token)), (BTN_NO, cb_payload(CB_NO, session_token))]]


def city_keyboard(session_token: str) -> list[list[tuple[str, str]]]:
    return [[(BTN_MSK, cb_payload(CB_MSK, session_token))], [(BTN_KRSK, cb_payload(CB_KRSK, session_token))]]


def send_stylist_cta(*, channel: str, bot_user_id: str, bot_chat_id: str, session_token: str) -> None:
    rows = stylist_cta_keyboard(session_token)
    if channel == "telegram":
        tg_send_text(bot_chat_id or bot_user_id, MSG_STYLIST_CTA, reply_markup=_tg_inline_keyboard(rows))
        return
    max_client.send_text_with_buttons(max_bot_token(), "user_id", str(bot_user_id), MSG_STYLIST_CTA, rows)


def send_city_choice(*, channel: str, bot_user_id: str, bot_chat_id: str, session_token: str) -> None:
    rows = city_keyboard(session_token)
    if channel == "telegram":
        tg_send_text(bot_chat_id or bot_user_id, MSG_CITY, reply_markup=_tg_inline_keyboard(rows))
        return
    max_client.send_text_with_buttons(max_bot_token(), "user_id", str(bot_user_id), MSG_CITY, rows)


def master_help_keyboard(
    city: str,
    *,
    return_url: str = "",
    ym_cid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> list[list[tuple[str, str]]]:
    marquiz, taplink = city_booking_urls(
        city,
        return_url=return_url,
        ym_cid=ym_cid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    return [[(BTN_PICK_MASTER, marquiz)], [(BTN_KNOW_MASTER, taplink)]]


def send_master_help(
    *,
    channel: str,
    bot_user_id: str,
    bot_chat_id: str,
    city: str,
    return_url: str = "",
    ym_cid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
    **_ignored: str,
) -> None:
    rows = master_help_keyboard(
        city,
        return_url=return_url,
        ym_cid=ym_cid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    if channel == "telegram":
        tg_send_text(bot_chat_id or bot_user_id, MSG_MASTER_HELP, reply_markup=_tg_link_keyboard(rows))
        return
    max_client.send_text_with_link_buttons(max_bot_token(), "user_id", str(bot_user_id), MSG_MASTER_HELP, rows)


def send_results_to_user(
    *,
    channel: str,
    bot_user_id: str,
    bot_chat_id: str,
    name: str,
    images: Iterable[Path],
    job_id: str = "",
    session_token: str = "",
) -> None:
    paths = [p for p in images if p.exists()]
    hello = "Ваши варианты образа от SOCO.salon готовы."

    if channel == "telegram":
        chat = bot_chat_id or bot_user_id
        tg_send_text(chat, hello)
        for i, path in enumerate(paths, 1):
            tg_send_photo(chat, path, caption=f"Вариант {i}")
        tg_send_text(chat, MSG_RESULT_NOTE)
        if session_token:
            send_stylist_cta(
                channel=channel,
                bot_user_id=bot_user_id,
                bot_chat_id=bot_chat_id,
                session_token=session_token,
            )
        return

    token = max_bot_token()
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN not configured")
    kind, value = "user_id", str(bot_user_id)
    max_client.send_text(token, kind, value, hello)
    public_base = os.getenv("TRYON_PUBLIC_URL", "https://primerka.soco-salon.ru").rstrip("/")
    for i, path in enumerate(paths, 1):
        pub = f"{public_base}/api/results/{job_id}/{path.name}" if job_id else ""
        max_client.send_image_smart(
            token,
            kind,
            value,
            path,
            public_url=pub,
            caption=f"Вариант {i}",
        )
    max_client.send_text(token, kind, value, MSG_RESULT_NOTE)
    if session_token:
        send_stylist_cta(
            channel=channel,
            bot_user_id=bot_user_id,
            bot_chat_id=bot_chat_id,
            session_token=session_token,
        )


def notify_stylist_interest(
    *,
    name: str,
    phone: str,
    city: str,
    channel: str,
    job_id: str = "",
    generation_id: str = "",
    ym_cid: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
) -> list[str]:
    """Owner lead alerts temporarily disabled; client dialog still works."""
    return []


def notify_owner_gate(
    *,
    name: str,
    phone: str,
    channel: str,
    token: str,
    ym_cid: str = "",
) -> list[str]:
    """Deprecated: do not notify on try-on start. Kept for old callers."""
    return []


def notify_tryon_completed(
    *,
    name: str,
    phone: str,
    job_id: str,
    before_name: str,
    after_names: list[str],
    client_id: str = "",
    city: str = "",
) -> list[str]:
    """Owner lead alerts temporarily disabled."""
    return []


def set_telegram_webhook(public_url: str, secret: str) -> dict:
    _tg_require_configured()
    url = _tg_endpoint("setWebhook")
    payload = {
        "url": f"{public_url.rstrip('/')}/api/bots/telegram",
        "secret_token": secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers=_tg_headers(),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def set_max_webhook(public_url: str, secret: str) -> dict:
    token = max_bot_token()
    payload = {
        "url": f"{public_url.rstrip('/')}/api/bots/max",
        "update_types": ["message_created", "bot_started", "message_callback"],
        "secret": secret,
    }
    req = urllib.request.Request(
        "https://platform-api2.max.ru/subscriptions",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    ctx = __import__("ssl")._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MAX subscribe HTTP {exc.code}: {detail}") from exc
