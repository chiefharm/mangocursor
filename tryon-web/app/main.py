"""SOCO AI hair try-on web service (Perfect Corp / YouCam)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import urllib.parse
import uuid
from pathlib import Path

import httpx
import segno
from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .bot_delivery import (
    CB_KRSK,
    CB_MSK,
    CB_NO,
    CB_WANT,
    CITY_BOOKING_URLS,
    MSG_THANKS_NO,
    booking_url_with_analytics,
    deep_link,
    normalize_return_url,
    notify_stylist_interest,
    notify_tryon_completed,
    parse_cb_payload,
    send_city_choice,
    send_master_help,
    send_processing_notice,
    send_results_to_user,
    telegram_bot_token,
    tg_answer_callback,
    tg_send_text,
)
from .clients import PHOTO_RETENTION_DAYS, ClientStore
from .geo_gate import GEO_GATE_ENABLED, check_client_geo
from .lead_notify import send_lead_email
from .max_client import notify_lead
from .perfectcorp import PerfectCorpClient, PerfectCorpError
from .sessions import (
    MONTHLY_LIMIT,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING_BOT,
    STATUS_PROCESSING,
    STATUS_READY,
    SessionStore,
    normalize_phone,
)
from .staff_auth import STAFF_COOKIE, StaffAuthStore
from .watermark import apply_watermark, downscale_jpeg, mirror_selfie

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# Also pick Telegram token from mango-pipeline if tryon .env lacks it
load_dotenv("/opt/mango-pipeline/.env")

DATA_DIR = Path(os.getenv("TRYON_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

STORE = SessionStore(DATA_DIR / "sessions.sqlite3")
CLIENTS = ClientStore(DATA_DIR / "clients.sqlite3")
STAFF = StaffAuthStore(DATA_DIR / "clients.sqlite3")

# Yandex Metrika counter for soco-salon.ru (сквозная аналитика MVP)
METRIKA_COUNTER_ID = int(os.getenv("METRIKA_COUNTER_ID", "64069270") or "64069270")


def _analytics_from_form(
    *,
    ym_cid: str = "",
    yandex_client_id: str = "",
    yclid: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_content: str = "",
    utm_term: str = "",
) -> dict[str, str]:
    return {
        "ym_cid": (ym_cid or yandex_client_id or "").strip()[:64],
        "yclid": (yclid or "").strip()[:255],
        "utm_source": (utm_source or "").strip()[:255],
        "utm_medium": (utm_medium or "").strip()[:255],
        "utm_campaign": (utm_campaign or "").strip()[:255],
        "utm_content": (utm_content or "").strip()[:255],
        "utm_term": (utm_term or "").strip()[:255],
    }


def _analytics_kwargs_from_session(sess) -> dict[str, str]:
    return {
        "generation_id": sess.token,
        "ym_cid": sess.ym_cid or "",
        "yclid": sess.yclid or "",
        "utm_source": sess.utm_source or "",
        "utm_medium": sess.utm_medium or "",
        "utm_campaign": sess.utm_campaign or "",
        "utm_content": sess.utm_content or "",
        "utm_term": sess.utm_term or "",
    }


_RETURN_URL_KEYS = ("return_url", "from", "site")


def _is_primerka_host(hostname: str) -> bool:
    host = (hostname or "").lower()
    return host == "primerka.soco-salon.ru" or host.endswith(".primerka.soco-salon.ru")


def _return_url_from_request(request: Request, form_value: str = "") -> str:
    url = normalize_return_url(form_value)
    if url:
        return url

    ref = (request.headers.get("referer") or "").strip()
    if not ref:
        return ""

    try:
        parts = urllib.parse.urlsplit(ref)
        if _is_primerka_host(parts.hostname):
            q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
            for key in _RETURN_URL_KEYS:
                for val in q.get(key, []):
                    candidate = normalize_return_url(val)
                    host = urllib.parse.urlsplit(candidate).hostname
                    if candidate and not _is_primerka_host(host):
                        return candidate
            return ""

        candidate = normalize_return_url(ref)
        host = urllib.parse.urlsplit(candidate).hostname
        if candidate and not _is_primerka_host(host):
            return candidate
    except ValueError:
        pass
    return ""

MAX_REFS = 2
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
PHONE_RE = re.compile(r"^[\d\s+\-()]{7,20}$")
MAX_CONCURRENT_TRYONS = max(1, int(os.getenv("TRYON_MAX_CONCURRENT", "1")))
MAX_QUEUE_WAIT_SEC = float(os.getenv("TRYON_QUEUE_WAIT_SEC", "120"))
WEBHOOK_SECRET = os.getenv("TRYON_BOT_WEBHOOK_SECRET", "").strip() or "soco-tryon-hook"
TRYON_MOCK = os.getenv("TRYON_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}
STAFF_COOKIE_SECURE = os.getenv("TRYON_STAFF_COOKIE_SECURE", "1").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title="SOCO AI Try-On", version="0.7.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

PORTFOLIO_DIR = BASE_DIR / "static" / "portfolio"
PORTFOLIO_MANIFEST = PORTFOLIO_DIR / "manifest.json"


@app.on_event("startup")
async def _startup_purge() -> None:
    try:
        n = CLIENTS.purge_expired(UPLOAD_DIR, RESULT_DIR)
        if n:
            print(f"purged {n} expired try-on jobs (>{PHOTO_RETENTION_DAYS}d)")
    except Exception as exc:  # noqa: BLE001
        print("purge_failed", exc)

_tryon_sem = asyncio.Semaphore(MAX_CONCURRENT_TRYONS)
_tryon_inflight = 0
_tryon_lock = asyncio.Lock()
_bg_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _notify_user_text(sess, text: str) -> None:
    try:
        if sess.channel == "telegram":
            from .bot_delivery import tg_send_text

            tg_send_text(sess.bot_chat_id or sess.bot_user_id, text)
        else:
            from . import max_client
            from .bot_delivery import max_bot_token

            max_client.send_text(max_bot_token(), "user_id", str(sess.bot_user_id), text)
    except Exception:
        pass


def _staged_paths(token: str) -> tuple[Path | None, list[Path]]:
    job_dir = UPLOAD_DIR / token
    if not job_dir.exists():
        return None, []
    befores = sorted(job_dir.glob("before*"))
    before = befores[0] if befores else None
    refs = sorted(job_dir.glob("ref_*.jpg")) + sorted(job_dir.glob("ref_*.jpeg"))
    # also any ref_*
    if not refs:
        refs = [p for p in sorted(job_dir.glob("ref_*")) if p.is_file()]
    return before, refs


def _client() -> PerfectCorpClient:
    key = os.getenv("PERFECTCORP_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=500, detail="PERFECTCORP_API_KEY is not configured")
    return PerfectCorpClient(key)


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else ""


async def _save_upload(file: UploadFile, dest: Path) -> None:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="File too large (max 8MB)")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file")


async def _download_and_watermark(url: str, out: Path, *, watermark: bool = True) -> None:
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        img = await http.get(url)
        img.raise_for_status()
        out.write_bytes(img.content)
    if watermark:
        await asyncio.to_thread(apply_watermark, out)


def _job_images(job_id: str) -> list[Path]:
    uploads = UPLOAD_DIR / job_id
    results = RESULT_DIR / job_id
    paths: list[Path] = []
    if uploads.exists():
        for p in sorted(uploads.glob("before*")):
            if p.is_file():
                paths.append(p)
    if results.exists():
        for p in sorted(results.glob("after_*.jpg")):
            if p.is_file():
                paths.append(p)
    return paths


def _after_images(job_id: str) -> list[Path]:
    results = RESULT_DIR / job_id
    if not results.exists():
        return []
    return [p for p in sorted(results.glob("after_*.jpg")) if p.is_file()]


def _load_portfolio_manifest() -> dict:
    if not PORTFOLIO_MANIFEST.exists():
        return {"categories": []}
    try:
        return json.loads(PORTFOLIO_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {"categories": []}


def _portfolio_item_path(item_id: str) -> Path | None:
    """Resolve portfolio id like zhen_dlinnye_01 → absolute image path."""
    item_id = (item_id or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*_\d{2}", item_id):
        return None
    manifest = _load_portfolio_manifest()
    for cat in manifest.get("categories") or []:
        for item in cat.get("items") or []:
            if item.get("id") != item_id:
                continue
            src = str(item.get("src") or "")
            # src is /static/portfolio/...
            if src.startswith("/static/"):
                path = BASE_DIR / src.lstrip("/")
            else:
                path = PORTFOLIO_DIR / Path(src).name
            if path.exists() and path.is_file():
                return path
            # fallback by id glob
            cat_id = cat.get("id") or item_id.split("_")[0]
            for p in (PORTFOLIO_DIR / cat_id).glob(f"{item_id}.*"):
                if p.is_file():
                    return p
    return None


def _require_staff(session_token: str | None) -> object:
    user = STAFF.verify_token((session_token or "").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Нужен вход в кабинет сотрудника")
    return user


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/staff")
async def staff_index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "staff.html")


@app.post("/api/staff/login")
async def staff_login(
    phone: str = Form(...),
    password: str = Form(...),
) -> JSONResponse:
    user = STAFF.authenticate(phone, password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный телефон или пароль")
    token = STAFF.issue_token(user.phone)
    resp = JSONResponse({"ok": True, "phone": user.phone, "name": user.name})
    resp.set_cookie(
        key=STAFF_COOKIE,
        value=token,
        httponly=True,
        secure=STAFF_COOKIE_SECURE,
        samesite="lax",
        max_age=12 * 60 * 60,
    )
    return resp


@app.post("/api/staff/logout")
async def staff_logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(STAFF_COOKIE)
    return resp


@app.get("/api/staff/me")
async def staff_me(soco_staff_session: str | None = Cookie(default=None)) -> JSONResponse:
    user = _require_staff(soco_staff_session)
    return JSONResponse({"ok": True, "phone": user.phone, "name": user.name})  # type: ignore[attr-defined]


_QR_ALLOWED_PREFIXES = ("https://t.me/", "https://max.ru/")


@app.get("/api/qr.png")
async def qr_png(url: str = Query(..., max_length=512)) -> Response:
    """QR for bot deep links (desktop → phone scan)."""
    link = (url or "").strip()
    if not link or not any(link.startswith(prefix) for prefix in _QR_ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail="Недопустимая ссылка для QR")
    try:
        qr = segno.make(link, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=8, border=2)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Не удалось создать QR") from exc
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/health")
async def health() -> dict:
    has_key = bool(os.getenv("PERFECTCORP_API_KEY", "").strip())
    has_max = bool(os.getenv("MAX_BOT_TOKEN", "").strip())
    has_tg = bool(telegram_bot_token())
    has_smtp = bool(os.getenv("SMTP_HOST", "").strip() and os.getenv("SMTP_PASSWORD", "").strip())
    return {
        "ok": True,
        "perfectcorp_configured": has_key,
        "max_configured": has_max,
        "telegram_configured": has_tg,
        "smtp_configured": has_smtp,
        "tryon_inflight": _tryon_inflight,
        "tryon_max_concurrent": MAX_CONCURRENT_TRYONS,
        "monthly_limit": MONTHLY_LIMIT,
        "geo_gate": GEO_GATE_ENABLED,
        "photo_retention_days": PHOTO_RETENTION_DAYS,
        "flow": "contacts_on_submit",
        "mock": TRYON_MOCK,
    }


@app.get("/api/portfolio")
async def portfolio() -> JSONResponse:
    data = _load_portfolio_manifest()
    return JSONResponse(data)


@app.post("/api/consent")
async def consent(request: Request) -> JSONResponse:
    """Deprecated: contacts are collected on /api/tryon submit."""
    raise HTTPException(
        status_code=410,
        detail="Обновите страницу. Контакты теперь запрашиваются при нажатии «Примерить».",
    )


@app.post("/api/submit")
async def submit_tryon(
    request: Request,
    before: UploadFile = File(...),
    refs: list[UploadFile] = File(...),
    phone: str = Form(...),
    channel: str = Form(...),
    name: str = Form(""),
    return_url: str = Form(""),
) -> JSONResponse:
    """Legacy bot-gate submit (kept for old clients). Prefer /api/consent + /api/tryon."""
    channel = (channel or "").strip().lower()
    if channel not in {"max", "telegram"}:
        raise HTTPException(status_code=400, detail="Выберите мессенджер: MAX или Telegram")
    if not refs:
        raise HTTPException(status_code=400, detail="Загрузите хотя бы 1 референс")
    if len(refs) > MAX_REFS:
        raise HTTPException(status_code=400, detail=f"Max {MAX_REFS} reference photos")
    phone_raw = (phone or "").strip()
    if not PHONE_RE.match(phone_raw):
        raise HTTPException(status_code=400, detail="Укажите корректный телефон")
    phone_n = normalize_phone(phone_raw)
    if len(re.sub(r"\D", "", phone_n)) < 10:
        raise HTTPException(status_code=400, detail="Укажите корректный телефон")
    name_n = " ".join((name or "").strip().split())

    ip = _client_ip(request)
    ok, reason = STORE.check_limits(phone_n, ip)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)

    sess = STORE.create(
        phone=phone_n,
        name=name_n,
        channel=channel,
        ip=ip,
        return_url=_return_url_from_request(request, return_url),
    )
    job_dir = UPLOAD_DIR / sess.token
    job_dir.mkdir(parents=True, exist_ok=True)

    before_path = job_dir / f"before{Path(before.filename or 'before.jpg').suffix or '.jpg'}"
    await _save_upload(before, before_path)
    already = "_mirror" in (before.filename or "").lower() or "_mirror" in before_path.name.lower()
    try:
        if not already:
            before_path = await asyncio.to_thread(mirror_selfie, before_path)
        else:
            before_path = await asyncio.to_thread(downscale_jpeg, before_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Photo process failed: {exc}") from exc

    for i, ref in enumerate(refs, 1):
        suffix = Path(ref.filename or f"ref{i}.jpg").suffix or ".jpg"
        path = job_dir / f"ref_{i}{suffix}"
        await _save_upload(ref, path)
        try:
            await asyncio.to_thread(downscale_jpeg, path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Ref process failed: {exc}") from exc

    link = deep_link(channel, sess.token)
    # Do not notify owner on start — only after successful try-on (onsite flow).
    return JSONResponse(
        {
            "ok": True,
            "session_token": sess.token,
            "channel": channel,
            "deep_link": link,
            "status": STATUS_PENDING_BOT,
            "message": "Откройте бота. Результат придёт туда — на сайт возвращаться не нужно.",
        }
    )


@app.post("/api/gate")
async def gate_start_legacy(request: Request) -> JSONResponse:
    """Deprecated: contacts-only gate. Prefer /api/submit with photos."""
    raise HTTPException(
        status_code=410,
        detail="Обновите страницу (Ctrl+F5). Нужна новая версия формы.",
    )


@app.get("/api/session/{token}")
async def session_status(token: str) -> JSONResponse:
    sess = STORE.get(token)
    if not sess:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return JSONResponse(
        {
            "ok": True,
            "session_token": sess.token,
            "generation_id": sess.token,
            "channel": sess.channel,
            "unlocked": sess.unlocked,
            "status": sess.status,
            "error": sess.error,
            "name": sess.name,
            "phone": sess.phone,
            "job_id": sess.job_id,
            "ym_cid": sess.ym_cid or None,
            "deep_link": deep_link(sess.channel, sess.token),
        }
    )


def _unlock_payload(
    payload: str,
    *,
    user_id: str,
    chat_id: str = "",
    channel: str = "",
) -> bool:
    sess = STORE.unlock_by_payload(payload, bot_user_id=user_id, bot_chat_id=chat_id or user_id)
    if not sess:
        return False
    if channel in {"max", "telegram"}:
        STORE.set_channel(sess.token, channel)
        sess = STORE.get(sess.token) or sess
    # Already have generated photos → send them to the bot, do not re-run YouCam
    if sess.job_id and _after_images(sess.job_id):
        try:
            loop = asyncio.get_running_loop()
            _track_task(loop.create_task(_deliver_existing_results(sess.token)))
        except RuntimeError:
            pass
        return True
    channel_name = channel if channel in {"max", "telegram"} else (sess.channel or "telegram")
    try:
        send_processing_notice(
            channel=channel_name,
            bot_user_id=sess.bot_user_id,
            bot_chat_id=sess.bot_chat_id,
            return_url=sess.return_url,
            **_analytics_kwargs_from_session(sess),
        )
    except Exception:
        pass
    try:
        loop = asyncio.get_running_loop()
        _track_task(loop.create_task(_process_session_job(sess.token)))
    except RuntimeError:
        pass
    return True


async def _deliver_existing_results(token: str) -> None:
    sess = STORE.get(token)
    if not sess or not sess.job_id:
        return
    after_paths = _after_images(sess.job_id)
    if not after_paths:
        _notify_user_text(sess, "Не нашли готовые фото. Сделайте примерку ещё раз на сайте.")
        return
    channel = sess.channel if sess.channel in {"max", "telegram"} else "telegram"
    try:
        await asyncio.to_thread(
            send_results_to_user,
            channel=channel,
            bot_user_id=sess.bot_user_id,
            bot_chat_id=sess.bot_chat_id,
            name=sess.name,
            images=after_paths,
            job_id=sess.job_id,
            session_token=token,
        )
        STORE.mark_done(token, sess.job_id)
    except Exception as exc:  # noqa: BLE001
        STORE.mark_error(token, f"Доставка: {exc}")
        _notify_user_text(
            sess,
            "Не удалось отправить фото в чат. Напишите нам — перешлём вручную.",
        )


def _resolve_session_for_cb(session_token: str, bot_user_id: str):
    if session_token:
        sess = STORE.get(session_token)
        if sess:
            return sess
    return STORE.latest_by_bot_user(bot_user_id)


def _handle_dialog_action(
    *,
    channel: str,
    bot_user_id: str,
    bot_chat_id: str,
    action: str,
    session_token: str,
) -> None:
    sess = _resolve_session_for_cb(session_token, bot_user_id)
    if not sess:
        return
    chat = bot_chat_id or sess.bot_chat_id or sess.bot_user_id
    uid = bot_user_id or sess.bot_user_id
    token = sess.token

    if action == CB_WANT:
        send_city_choice(
            channel=channel,
            bot_user_id=uid,
            bot_chat_id=chat,
            session_token=token,
        )
        return

    if action == CB_NO:
        _notify_user_text(sess, MSG_THANKS_NO)
        return

    if action in {CB_MSK, CB_KRSK}:
        city = "moscow" if action == CB_MSK else "krasnoyarsk"
        # Owner «Новая заявка» / generation_id alerts temporarily disabled.
        try:
            notify_stylist_interest(
                name=sess.name,
                phone=sess.phone,
                city=city,
                channel=channel,
                job_id=sess.job_id or sess.token,
                generation_id=sess.token,
                ym_cid=sess.ym_cid,
                yclid=sess.yclid,
                utm_source=sess.utm_source,
                utm_medium=sess.utm_medium,
                utm_campaign=sess.utm_campaign,
            )
        except Exception:
            pass
        try:
            send_master_help(
                channel=channel,
                bot_user_id=uid,
                bot_chat_id=chat,
                city=city,
                return_url=sess.return_url,
                ym_cid=sess.ym_cid,
                utm_source=sess.utm_source,
                utm_medium=sess.utm_medium,
                utm_campaign=sess.utm_campaign,
                utm_content=sess.utm_content,
                utm_term=sess.utm_term,
            )
        except Exception:
            pass


async def _process_session_job(token: str) -> None:
    claimed = STORE.claim_processing(token)
    if not claimed:
        return
    sess = claimed
    global _tryon_inflight
    try:
        await asyncio.wait_for(_tryon_sem.acquire(), timeout=MAX_QUEUE_WAIT_SEC)
    except asyncio.TimeoutError:
        STORE.mark_error(token, "Очередь переполнена, попробуйте позже")
        _notify_user_text(sess, "Сейчас большая очередь. Напишите нам или попробуйте позже.")
        return

    async with _tryon_lock:
        _tryon_inflight += 1
    try:
        before_path, ref_paths = _staged_paths(token)
        if not before_path or not ref_paths:
            STORE.mark_error(token, "Фото не найдены на сервере")
            _notify_user_text(sess, "Не нашли ваши фото. Загрузите снова на сайте примерки.")
            return

        ok, reason = STORE.check_limits(sess.phone, sess.ip)
        if not ok:
            STORE.mark_error(token, reason)
            _notify_user_text(sess, reason)
            return

        job_id = token  # reuse staged folder id
        result_job_dir = RESULT_DIR / job_id
        result_job_dir.mkdir(parents=True, exist_ok=True)

        if TRYON_MOCK:
            results = await _mock_tryon_results(
                before_path=before_path,
                ref_paths=ref_paths,
                job_id=job_id,
                result_job_dir=result_job_dir,
            )
        else:
            client = _client()
            src_file_id = await client.upload_file(before_path)
            ref_ids: list[str] = []
            for p in ref_paths:
                ref_ids.append(await client.upload_file(p))

            results = []
            for i, ref_id in enumerate(ref_ids, 1):
                results.append(await _one_transfer(client, job_id, result_job_dir, src_file_id, i, ref_id))

        ok_count = sum(1 for r in results if r.get("status") == "ok")
        if ok_count == 0:
            STORE.mark_error(token, "Сервис примерки не вернул результат")
            _notify_user_text(sess, "Не удалось сделать примерку. Попробуйте ещё раз с сайта.")
            return

        if not TRYON_MOCK:
            STORE.record_usage(phone=sess.phone, ip=sess.ip, session_token=token)
        after_paths = _after_images(job_id)
        try:
            await asyncio.to_thread(
                send_results_to_user,
                channel=sess.channel,
                bot_user_id=sess.bot_user_id,
                bot_chat_id=sess.bot_chat_id,
                name=sess.name,
                images=after_paths,
                job_id=job_id,
                session_token=token,
            )
            STORE.mark_done(token, job_id)
        except Exception as exc:  # noqa: BLE001
            STORE.mark_error(token, f"Доставка: {exc}")
            _notify_user_text(
                sess,
                "Примерка готова, но фото не отправилось. Напишите нам — перешлём вручную.",
            )
    except Exception as exc:  # noqa: BLE001
        STORE.mark_error(token, str(exc)[:500])
        _notify_user_text(sess, "Ошибка при генерации. Попробуйте ещё раз с сайта примерки.")
    finally:
        async with _tryon_lock:
            _tryon_inflight -= 1
        _tryon_sem.release()


@app.post("/api/bots/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")
    update = await request.json()

    cq = update.get("callback_query") or {}
    if cq:
        cq_id = str(cq.get("id") or "")
        data = str(cq.get("data") or "")
        from_user = cq.get("from") or {}
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        user_id = str(from_user.get("id") or "")
        chat_id = str(chat.get("id") or user_id)
        action, session_token = parse_cb_payload(data)
        try:
            tg_answer_callback(cq_id)
        except Exception:
            pass
        try:
            _handle_dialog_action(
                channel="telegram",
                bot_user_id=user_id,
                bot_chat_id=chat_id,
                action=action,
                session_token=session_token,
            )
        except Exception:
            pass
        return {"ok": True}

    message = update.get("message") or update.get("edited_message") or {}
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = str(chat.get("id") or "")
    user_id = str(user.get("id") or chat_id)
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        if payload:
            _unlock_payload(payload, user_id=user_id, chat_id=chat_id, channel="telegram")
        else:
            try:
                tg_send_text(
                    chat_id,
                    "Это бот AI-примерки SOCO.\nОткройте ссылку с сайта примерки после загрузки фото.",
                )
            except Exception:
                pass
    return {"ok": True}


@app.post("/api/bots/max")
async def max_webhook(
    request: Request,
    x_max_bot_api_secret: str | None = Header(default=None),
) -> dict:
    if WEBHOOK_SECRET and x_max_bot_api_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret")
    update = await request.json()

    try:
        log_path = DATA_DIR / "max_webhook_last.json"
        log_path.write_text(
            __import__("json").dumps(update, ensure_ascii=False, default=str)[:8000],
            encoding="utf-8",
        )
    except Exception:
        pass

    utype = str(update.get("update_type") or update.get("type") or "")
    payload = str(update.get("payload") or "")
    user = update.get("user") or {}
    user_id = str(user.get("user_id") or user.get("id") or "")
    chat_id = str(update.get("chat_id") or user_id)

    # Inline button press
    if utype == "message_callback" or update.get("callback"):
        cb = update.get("callback") or {}
        cb_id = str(cb.get("callback_id") or update.get("callback_id") or "")
        cb_payload = str(cb.get("payload") or update.get("payload") or "")
        cb_user = cb.get("user") or user or {}
        if not user_id:
            user_id = str(cb_user.get("user_id") or cb_user.get("id") or "")
        action, session_token = parse_cb_payload(cb_payload)
        try:
            from . import max_client
            from .bot_delivery import max_bot_token

            max_client.answer_callback(max_bot_token(), cb_id)
        except Exception:
            pass
        try:
            _handle_dialog_action(
                channel="max",
                bot_user_id=user_id,
                bot_chat_id=chat_id or user_id,
                action=action,
                session_token=session_token,
            )
        except Exception:
            pass
        return {"ok": True}

    if not payload:
        for key in ("start_payload", "start", "payload"):
            nested = update.get(key)
            if nested:
                payload = str(nested)
                break

    if utype == "bot_started" and payload and user_id:
        _unlock_payload(payload, user_id=user_id, chat_id=chat_id, channel="max")
        return {"ok": True}

    message = update.get("message") or {}
    sender = message.get("sender") or message.get("from") or user or {}
    if not user_id:
        user_id = str(sender.get("user_id") or sender.get("id") or "")
    body = message.get("body") or {}
    text = str(body.get("text") or message.get("text") or "").strip()
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else payload
    if (payload or text) and user_id:
        token_candidate = (payload or text).strip()
        if re.fullmatch(r"[a-fA-F0-9]{8,32}", token_candidate):
            _unlock_payload(token_candidate, user_id=user_id, chat_id=chat_id or user_id, channel="max")
    return {"ok": True}


async def _mock_tryon_results(
    *,
    before_path: Path,
    ref_paths: list[Path],
    job_id: str,
    result_job_dir: Path,
    watermark: bool = True,
) -> list[dict]:
    """UI-test mode: no Perfect Corp calls. Copy before→after (optional watermark)."""
    await asyncio.sleep(1.2)  # short fake progress
    results: list[dict] = []
    n = max(1, len(ref_paths))
    for i in range(1, n + 1):
        out = result_job_dir / f"after_{i}.jpg"
        shutil.copy2(before_path, out)
        if watermark:
            try:
                await asyncio.to_thread(apply_watermark, out)
            except Exception:
                pass
        results.append(
            {
                "index": i,
                "status": "ok",
                "mock": True,
                "result_url": f"/api/results/{job_id}/after_{i}.jpg",
                "url": f"/api/results/{job_id}/after_{i}.jpg",
            }
        )
    return results


async def _run_tryon_direct(
    *,
    token: str,
    sess,
    before_path: Path,
    ref_paths: list[Path],
    watermark: bool = False,
) -> tuple[str, list[str]]:
    global _tryon_inflight
    try:
        await asyncio.wait_for(_tryon_sem.acquire(), timeout=MAX_QUEUE_WAIT_SEC)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=429, detail="Очередь переполнена, попробуйте позже") from exc

    async with _tryon_lock:
        _tryon_inflight += 1
    try:
        job_id = token
        result_job_dir = RESULT_DIR / job_id
        result_job_dir.mkdir(parents=True, exist_ok=True)
        if TRYON_MOCK:
            await _mock_tryon_results(
                before_path=before_path,
                ref_paths=ref_paths,
                job_id=job_id,
                result_job_dir=result_job_dir,
                watermark=watermark,
            )
        else:
            client = _client()
            src_file_id = await client.upload_file(before_path)
            ref_ids: list[str] = []
            for p in ref_paths:
                ref_ids.append(await client.upload_file(p))
            for i, ref_id in enumerate(ref_ids, 1):
                await _one_transfer(
                    client, job_id, result_job_dir, src_file_id, i, ref_id, watermark=watermark
                )

        after_paths = _after_images(job_id)
        if not after_paths:
            raise HTTPException(status_code=502, detail="Не удалось получить результат примерки")
        STORE.mark_done(token, job_id)
        CLIENTS.mark_job(job_id, status="done")
        urls = [f"/api/results/{job_id}/{p.name}" for p in after_paths]
        return job_id, urls
    except HTTPException:
        STORE.mark_error(token, "staff try-on failed")
        CLIENTS.mark_job(token, status="error", error="staff try-on failed")
        raise
    except Exception as exc:  # noqa: BLE001
        STORE.mark_error(token, str(exc)[:500])
        CLIENTS.mark_job(token, status="error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Ошибка генерации: {exc}") from exc
    finally:
        async with _tryon_lock:
            _tryon_inflight -= 1
        _tryon_sem.release()


@app.post("/api/tryon")
async def tryon_onsite(
    request: Request,
    before: UploadFile = File(...),
    refs: list[UploadFile] = File(default=[]),
    portfolio_ids: str = Form(""),
    name: str = Form(""),
    phone: str = Form(""),
    consent: str = Form("1"),
    ym_cid: str = Form(""),
    yandex_client_id: str = Form(""),
    yclid: str = Form(""),
    utm_source: str = Form(""),
    utm_medium: str = Form(""),
    utm_campaign: str = Form(""),
    utm_content: str = Form(""),
    utm_term: str = Form(""),
    return_url: str = Form(""),
) -> JSONResponse:
    """Save photos and wait for bot activation before YouCam generation."""
    ip = _client_ip(request)
    geo_ok, geo_reason = check_client_geo(ip)
    if not geo_ok:
        raise HTTPException(status_code=403, detail=geo_reason)

    name_n = " ".join((name or "").strip().split()) or "Клиент сайта"
    phone_raw = (phone or "").strip()
    ok_consent = str(consent or "").strip().lower() in {"1", "true", "yes", "on"}
    if not ok_consent:
        raise HTTPException(status_code=400, detail="Нужно согласие на обработку персональных данных")
    if phone_raw and PHONE_RE.match(phone_raw):
        phone_n = normalize_phone(phone_raw)
    else:
        # Messenger-first flow: allow try-on start without phone on site.
        phone_n = f"anon-{ip or 'na'}"

    refs_list = list(refs or [])
    port_ids = [x.strip() for x in (portfolio_ids or "").split(",") if x.strip()]
    if not refs_list and not port_ids:
        raise HTTPException(status_code=400, detail="Загрузите референс или выберите из портфолио")
    if len(refs_list) + len(port_ids) > MAX_REFS:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_REFS} референса")

    if phone_n.startswith("anon-"):
        if MONTHLY_LIMIT > 0 and STORE.usage_count_ip(ip) >= MONTHLY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"На одном устройстве доступно {MONTHLY_LIMIT} примерки в месяц. "
                    "На консультации с мастером количество примерок не ограничено."
                ),
            )
    else:
        ok, reason = STORE.check_limits(phone_n, ip)
        if not ok:
            raise HTTPException(status_code=429, detail=reason)

    analytics = _analytics_from_form(
        ym_cid=ym_cid,
        yandex_client_id=yandex_client_id,
        yclid=yclid,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_content=utm_content,
        utm_term=utm_term,
    )
    client_row = CLIENTS.upsert(phone=phone_n, name=name_n, ip=ip, consent=True)
    sess = STORE.create(
        phone=phone_n,
        name=name_n,
        channel="telegram",
        ip=ip,
        return_url=_return_url_from_request(request, return_url),
        **analytics,
    )
    token = sess.token

    # Stage uploads under session token; generation starts only after /start in bot.
    job_id = token
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    STORE.set_job(token, job_id)
    CLIENTS.create_job(job_id=job_id, client_id=client_row.client_id, status="processing")

    before_path = job_dir / f"before{Path(before.filename or 'before.jpg').suffix or '.jpg'}"
    await _save_upload(before, before_path)
    try:
        # Client mirrors selfie (before_mirror.jpg). Gallery upload is never flipped here.
        await asyncio.to_thread(downscale_jpeg, before_path)
    except Exception as exc:  # noqa: BLE001
        STORE.mark_error(token, f"Photo process failed: {exc}")
        CLIENTS.mark_job(job_id, status="error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Photo process failed: {exc}") from exc

    idx = 1
    for ref in refs_list:
        suffix = Path(ref.filename or f"ref{idx}.jpg").suffix or ".jpg"
        path = job_dir / f"ref_{idx}{suffix}"
        await _save_upload(ref, path)
        try:
            await asyncio.to_thread(downscale_jpeg, path)
        except Exception as exc:  # noqa: BLE001
            STORE.mark_error(token, f"Ref process failed: {exc}")
            CLIENTS.mark_job(job_id, status="error", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Ref process failed: {exc}") from exc
        idx += 1

    for pid in port_ids:
        src = _portfolio_item_path(pid)
        if not src:
            STORE.mark_error(token, f"Unknown portfolio id: {pid}")
            CLIENTS.mark_job(job_id, status="error", error=f"Unknown portfolio id: {pid}")
            raise HTTPException(status_code=400, detail=f"Референс портфолио не найден: {pid}")
        dest = job_dir / f"ref_{idx}{src.suffix or '.jpg'}"
        shutil.copy2(src, dest)
        try:
            await asyncio.to_thread(downscale_jpeg, dest)
        except Exception:
            pass
        idx += 1

    return JSONResponse(
        {
            "ok": True,
            "job_id": job_id,
            "client_id": client_row.client_id,
            "session_token": token,
            "generation_id": token,
            "ym_cid": analytics.get("ym_cid") or None,
            "retention_days": PHOTO_RETENTION_DAYS,
            "status": STATUS_PENDING_BOT,
            "max_link": deep_link("max", token),
            "telegram_link": deep_link("telegram", token),
            "message": "Активируйте бота в MAX или Telegram: после запустим генерацию и отправим результат в мессенджер.",
        }
    )


@app.post("/api/staff/tryon")
async def staff_tryon(
    request: Request,
    before: UploadFile = File(...),
    refs: list[UploadFile] = File(default=[]),
    portfolio_ids: str = Form(""),
    client_name: str = Form(...),
    client_phone: str = Form(""),
    soco_staff_session: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_staff(soco_staff_session)
    name_n = " ".join((client_name or "").strip().split())
    phone_raw = (client_phone or "").strip()
    if len(name_n) < 2:
        raise HTTPException(status_code=400, detail="Укажите имя клиента")
    # Phone optional in staff cabinet: unique synthetic id keeps CRM unique constraint.
    if phone_raw:
        if not PHONE_RE.match(phone_raw):
            raise HTTPException(status_code=400, detail="Укажите корректный телефон клиента")
        phone_n = normalize_phone(phone_raw)
        if len(re.sub(r"\D", "", phone_n)) < 10:
            raise HTTPException(status_code=400, detail="Укажите корректный телефон клиента")
    else:
        phone_n = f"+700{uuid.uuid4().hex[:10]}"

    refs_list = list(refs or [])
    port_ids = [x.strip() for x in (portfolio_ids or "").split(",") if x.strip()]
    if not refs_list and not port_ids:
        raise HTTPException(status_code=400, detail="Загрузите референс или выберите из портфолио")
    if len(refs_list) + len(port_ids) > MAX_REFS:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_REFS} референса")

    ip = _client_ip(request)
    client_row = CLIENTS.upsert(phone=phone_n, name=name_n, ip=ip, consent=True)
    sess = STORE.create_web_consent(phone=phone_n, name=name_n, ip=ip)
    token = sess.token
    job_id = token
    STORE.set_job(token, job_id)
    CLIENTS.create_job(job_id=job_id, client_id=client_row.client_id, status="processing")

    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    before_path = job_dir / f"before{Path(before.filename or 'before.jpg').suffix or '.jpg'}"
    await _save_upload(before, before_path)
    try:
        await asyncio.to_thread(downscale_jpeg, before_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Photo process failed: {exc}") from exc

    ref_paths: list[Path] = []
    idx = 1
    for ref in refs_list:
        suffix = Path(ref.filename or f"ref{idx}.jpg").suffix or ".jpg"
        path = job_dir / f"ref_{idx}{suffix}"
        await _save_upload(ref, path)
        try:
            await asyncio.to_thread(downscale_jpeg, path)
        except Exception:
            pass
        ref_paths.append(path)
        idx += 1
    for pid in port_ids:
        src = _portfolio_item_path(pid)
        if not src:
            raise HTTPException(status_code=400, detail=f"Референс портфолио не найден: {pid}")
        dest = job_dir / f"ref_{idx}{src.suffix or '.jpg'}"
        shutil.copy2(src, dest)
        try:
            await asyncio.to_thread(downscale_jpeg, dest)
        except Exception:
            pass
        ref_paths.append(dest)
        idx += 1

    job_id, result_urls = await _run_tryon_direct(
        token=token,
        sess=sess,
        before_path=before_path,
        ref_paths=ref_paths,
        watermark=False,
    )
    return JSONResponse(
        {
            "ok": True,
            "job_id": job_id,
            "session_token": token,
            "client_id": client_row.client_id,
            "client_name": client_row.name,
            "client_phone": client_row.phone,
            "created_at": sess.created_at,
            "retention_days": PHOTO_RETENTION_DAYS,
            "before_url": f"/api/uploads/{job_id}/{before_path.name}",
            "results": result_urls,
        }
    )


@app.get("/api/staff/generations")
async def staff_generations(
    limit: int = 100,
    offset: int = 0,
    q: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    include_expired: int = 0,
    soco_staff_session: str | None = Cookie(default=None),
) -> JSONResponse:
    _require_staff(soco_staff_session)
    rows = CLIENTS.recent_jobs(
        limit=limit,
        offset=offset,
        search=q,
        include_expired=bool(include_expired),
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    items = []
    for row in rows:
        before_url = None
        uploads = UPLOAD_DIR / row.job_id
        if uploads.exists():
            befores = sorted(uploads.glob("before*"))
            if befores:
                before_url = f"/api/uploads/{row.job_id}/{befores[0].name}"
        result_urls = [f"/api/results/{row.job_id}/{p.name}" for p in _after_images(row.job_id)]
        items.append(
            {
                "job_id": row.job_id,
                "client_id": row.client_id,
                "client_name": row.client_name,
                "client_phone": row.client_phone,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "status": row.status,
                "error": row.error,
                "before_url": before_url,
                "result_urls": result_urls,
            }
        )
    return JSONResponse({"ok": True, "items": items, "retention_days": PHOTO_RETENTION_DAYS})


@app.get("/api/booking-urls")
async def booking_urls() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "cities": {
                city: {"pick_master": urls[0], "know_master": urls[1]}
                for city, urls in CITY_BOOKING_URLS.items()
            },
        }
    )


@app.post("/api/booking-intent")
async def booking_intent(
    job_id: str = Form(""),
    client_id: str = Form(""),
    session_token: str = Form(""),
    city: str = Form(...),
    intent: str = Form(...),
    name: str = Form(""),
    phone: str = Form(""),
) -> JSONResponse:
    """Notify sales when user chose master-help path + city on the website."""
    city = (city or "").strip().lower()
    intent = (intent or "").strip().lower()
    if city not in {"moscow", "krasnoyarsk"}:
        raise HTTPException(status_code=400, detail="Выберите город")
    if intent not in {"pick_master", "know_master"}:
        raise HTTPException(status_code=400, detail="Неизвестный тип записи")

    name_n = " ".join((name or "").strip().split())
    phone_n = normalize_phone(phone) if phone else ""
    if client_id:
        client = CLIENTS.get(client_id.strip())
        if client:
            name_n = name_n or client.name
            phone_n = phone_n or client.phone
    sess = STORE.get((session_token or "").strip()) if session_token else None
    analytics = _analytics_kwargs_from_session(sess) if sess else {
        "generation_id": (session_token or "").strip(),
        "ym_cid": "",
        "yclid": "",
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "utm_content": "",
        "utm_term": "",
    }
    urls = CITY_BOOKING_URLS.get(city) or CITY_BOOKING_URLS["krasnoyarsk"]
    base = urls[0] if intent == "pick_master" else urls[1]
    target = booking_url_with_analytics(
        base,
        ym_cid=analytics.get("ym_cid") or "",
        utm_source=analytics.get("utm_source") or "",
        utm_medium=analytics.get("utm_medium") or "",
        utm_campaign=analytics.get("utm_campaign") or "",
        utm_content=analytics.get("utm_content") or "",
        utm_term=analytics.get("utm_term") or "",
    )

    # Bot lead only when client chose «Да, подобрать мастера»
    if intent == "pick_master":
        before_name = ""
        after_names: list[str] = []
        if job_id:
            uploads = UPLOAD_DIR / job_id
            if uploads.exists():
                befores = sorted(uploads.glob("before*"))
                if befores:
                    before_name = befores[0].name
            after_names = [p.name for p in _after_images(job_id)]
        try:
            await asyncio.to_thread(
                notify_tryon_completed,
                name=name_n or "Клиент сайта",
                phone=phone_n or "—",
                job_id=job_id or "",
                before_name=before_name,
                after_names=after_names,
                client_id=client_id or "",
                city=city,
            )
        except Exception:
            pass
        try:
            await asyncio.to_thread(
                send_lead_email,
                name=name_n or "Клиент сайта",
                phone=phone_n or "—",
                job_id=job_id or "web",
                images=_job_images(job_id) if job_id else [],
                intent="quote",
                client_id=client_id or "",
                **analytics,
            )
        except Exception:
            pass

    return JSONResponse(
        {
            "ok": True,
            "city": city,
            "intent": intent,
            "redirect_url": target,
            "client_id": client_id or None,
            "generation_id": analytics.get("generation_id") or None,
            "ym_cid": analytics.get("ym_cid") or None,
        }
    )


@app.post("/api/messenger")
async def messenger_links(
    session_token: str = Form(...),
    job_id: str = Form(...),
) -> JSONResponse:
    """Prepare bot deep-links to deliver already-generated photos to MAX/Telegram."""
    token = (session_token or "").strip()
    job_id = (job_id or "").strip()
    sess = STORE.get(token)
    if not sess:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if not job_id or not _after_images(job_id):
        raise HTTPException(status_code=400, detail="Нет готовых фото для отправки")

    STORE.prepare_messenger_delivery(token, job_id=job_id)
    return JSONResponse(
        {
            "ok": True,
            "session_token": token,
            "job_id": job_id,
            "max_link": deep_link("max", token),
            "telegram_link": deep_link("telegram", token),
            "message": "Откройте бота и нажмите Старт — пришлём фото в чат.",
        }
    )


@app.get("/api/client/{client_id}")
async def client_lookup(client_id: str) -> JSONResponse:
    """Lookup client + active jobs for sales / master (no secrets)."""
    client = CLIENTS.get(client_id.strip())
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    jobs = CLIENTS.jobs_for_client(client.client_id)
    return JSONResponse(
        {
            "ok": True,
            "client_id": client.client_id,
            "name": client.name,
            "phone": client.phone,
            "jobs": [
                {
                    "job_id": j.job_id,
                    "created_at": j.created_at,
                    "expires_at": j.expires_at,
                    "status": j.status,
                }
                for j in jobs
            ],
            "retention_days": PHOTO_RETENTION_DAYS,
        }
    )


async def _one_transfer(
    client: PerfectCorpClient,
    job_id: str,
    result_job_dir: Path,
    src_file_id: str,
    i: int,
    ref_id: str,
    *,
    watermark: bool = True,
) -> dict:
    try:
        task_id = await client.create_hair_transfer(
            src_file_id=src_file_id,
            ref_file_id=ref_id,
        )
        url = await client.wait_result(task_id)
        out = result_job_dir / f"after_{i}.jpg"
        try:
            await _download_and_watermark(url, out, watermark=watermark)
            return {"index": i, "status": "ok", "task_id": task_id}
        except Exception:
            return {"index": i, "status": "ok", "task_id": task_id, "remote": True}
    except PerfectCorpError as exc:
        payload = getattr(exc, "payload", None) or {}
        from .perfectcorp import _extract_result_url

        maybe = _extract_result_url(payload.get("data") or payload) if isinstance(payload, dict) else None
        if maybe:
            out = result_job_dir / f"after_{i}.jpg"
            try:
                await _download_and_watermark(maybe, out, watermark=watermark)
                return {"index": i, "status": "ok", "warning": str(exc)}
            except Exception:
                return {"index": i, "status": "ok", "remote": True, "warning": str(exc)}
        return {"index": i, "status": "error", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"index": i, "status": "error", "error": str(exc)}


@app.post("/api/lead")
async def lead(
    job_id: str = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    intent: str = Form("book"),
    client_id: str = Form(""),
    session_token: str = Form(""),
) -> JSONResponse:
    job_id = job_id.strip()
    name = " ".join(name.strip().split())
    phone = phone.strip()
    client_id = (client_id or "").strip()
    intent = (intent or "book").strip().lower()
    if intent not in {"book", "quote"}:
        intent = "book"
    if not job_id or not (UPLOAD_DIR / job_id).exists():
        raise HTTPException(status_code=400, detail="Сессия примерки не найдена. Сделайте примерку ещё раз.")
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Укажите имя")
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="Укажите корректный телефон")

    job = CLIENTS.get_job(job_id)
    if job and not client_id:
        client_id = job.client_id
    if not client_id:
        # ensure client exists for sales id
        client_row = CLIENTS.upsert(phone=normalize_phone(phone), name=name, consent=True)
        client_id = client_row.client_id
        if not job:
            CLIENTS.create_job(job_id=job_id, client_id=client_id, status="done")

    sess = STORE.get((session_token or "").strip()) if session_token else None
    analytics = _analytics_kwargs_from_session(sess) if sess else {
        "generation_id": (session_token or "").strip(),
        "ym_cid": "",
        "yclid": "",
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "utm_content": "",
        "utm_term": "",
    }

    images = _job_images(job_id)
    if not images:
        raise HTTPException(status_code=400, detail="Нет фото для заявки")

    max_errors = await asyncio.to_thread(
        notify_lead,
        name=name,
        phone=phone,
        job_id=job_id,
        images=images,
        intent=intent,
        client_id=client_id,
        **analytics,
    )
    email_error = None
    try:
        await asyncio.to_thread(
            send_lead_email,
            name=name,
            phone=phone,
            job_id=job_id,
            images=images,
            intent=intent,
            client_id=client_id,
            **analytics,
        )
    except Exception as exc:  # noqa: BLE001
        email_error = str(exc)

    if max_errors and email_error:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось отправить заявку. MAX: {'; '.join(max_errors)}; email: {email_error}",
        )

    return JSONResponse(
        {
            "ok": True,
            "intent": intent,
            "client_id": client_id,
            "max_ok": not max_errors,
            "email_ok": email_error is None,
            "warnings": {"max": max_errors, "email": email_error},
        }
    )


@app.get("/api/uploads/{job_id}/{filename}")
async def get_upload(job_id: str, filename: str) -> FileResponse:
    path = UPLOAD_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.get("/api/results/{job_id}/{filename}")
async def get_result(job_id: str, filename: str) -> FileResponse:
    path = RESULT_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.post("/api/cleanup")
async def cleanup(job_id: str = Form(...)) -> dict:
    for root in (UPLOAD_DIR / job_id, RESULT_DIR / job_id):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    return {"ok": True}
