"""Personal finance website — upload a bank statement, explain transfers."""

from __future__ import annotations

import calendar
import hashlib
import hmac
import os
import secrets
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .parse import ParseError, parse_statement
from .report import month_title
from .store import FinanceStore, public_tx
from .advice import build_digest
from .notify import send_after_import, send_after_review_cleared
from . import telegram as tg

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("FINANCE_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "ledger.sqlite"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_SUFFIX = {".csv", ".xlsx", ".xls", ".txt", ".pdf"}
COOKIE_NAME = "pf_session"
COOKIE_DAYS = 30

DEFAULT_EXPENSE = [
    "Продукты",
    "Кафе",
    "Транспорт",
    "Жильё",
    "Связь",
    "Здоровье",
    "Одежда",
    "Подарки",
    "Подписки",
    "Накопления",
]
DEFAULT_INCOME = ["Зарплата", "Дивиденды", "Возврат", "Подарок", "Проценты"]

app = FastAPI(title="Личные финансы", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
store = FinanceStore(DB_PATH)
if os.getenv("FINANCE_DEMO", "").strip() in {"1", "true", "yes"}:
    from .demo import seed_if_empty

    seed_if_empty(store)


def reset_data_dir(path: str | Path) -> None:
    """Used by tests to isolate the SQLite ledger."""
    global DATA_DIR, UPLOAD_DIR, DB_PATH, store
    DATA_DIR = Path(path)
    UPLOAD_DIR = DATA_DIR / "uploads"
    DB_PATH = DATA_DIR / "ledger.sqlite"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    store = FinanceStore(DB_PATH)
    if os.getenv("FINANCE_DEMO", "").strip() in {"1", "true", "yes"}:
        from .demo import seed_if_empty

        seed_if_empty(store)


def _password() -> str:
    return os.getenv("FINANCE_PASSWORD", "").strip()


def _secret() -> bytes:
    env = os.getenv("FINANCE_SESSION_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    path = DATA_DIR / ".session_secret"
    if path.is_file():
        return path.read_bytes().strip()
    token = secrets.token_hex(32)
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    return token.encode("utf-8")


def _auth_off() -> bool:
    return os.getenv("FINANCE_AUTH", "on").strip().lower() in {"0", "false", "no", "off"}


def _demo() -> bool:
    return os.getenv("FINANCE_DEMO", "").strip().lower() in {"1", "true", "yes"}


def _drive_on() -> bool:
    raw = os.getenv("FINANCE_DRIVE_ENABLED", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return not _demo()


def _sign(payload: str) -> str:
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _valid_cookie(raw: str | None) -> bool:
    if _auth_off():
        return True
    if not raw or "." not in raw:
        return False
    payload, sig = raw.rsplit(".", 1)
    expect = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return False
    try:
        issued = int(payload.split(":", 1)[0])
    except ValueError:
        return False
    return (time.time() - issued) < COOKIE_DAYS * 86400


def _is_authed(request: Request) -> bool:
    if _auth_off():
        return True
    if not _password():
        return True
    return _valid_cookie(request.cookies.get(COOKIE_NAME))


class AuthGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        open_paths = {"/api/login", "/api/health", "/", "/static/styles.css", "/static/app.js"}
        if path.startswith("/static/") or path in open_paths:
            return await call_next(request)
        if path.startswith("/api/") and not _is_authed(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(AuthGate)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "telegram": tg.telegram_enabled(),
        "auth_required": bool(_password()) and not _auth_off(),
    }


@app.get("/api/me")
async def me(request: Request) -> dict:
    return {
        "ok": True,
        "authed": _is_authed(request),
        "auth_required": bool(_password()) and not _auth_off(),
        "review_count": store.review_count() if _is_authed(request) else 0,
        "telegram": tg.telegram_enabled(),
        "demo": _demo(),
        "drive": _drive_on(),
    }


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    body = await request.json()
    password = str(body.get("password") or "")
    expected = _password()
    if not expected:
        raise HTTPException(status_code=400, detail="Пароль не задан в .env (FINANCE_PASSWORD)")
    if not hmac.compare_digest(password, expected):
        raise HTTPException(status_code=403, detail="Неверный пароль")
    token = _sign(f"{int(time.time())}:{secrets.token_hex(8)}")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_DAYS * 86400,
    )
    return resp


@app.post("/api/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.post("/api/import")
async def import_statement(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "statement.csv"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(status_code=400, detail="Нужен файл CSV, Excel или PDF")
    dest = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_name(filename)}"
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="Файл больше 12 МБ")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Пустой файл")
    try:
        txs = parse_statement(dest, filename=filename)
        result = store.import_transactions(txs, filename)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_from = result.period_from or date.today().isoformat()
    period_to = result.period_to or date.today().isoformat()
    summary = store.summary(period_from, period_to)
    prev_from, prev_to = store.previous_period(period_from, period_to)
    previous = store.summary(prev_from, prev_to)

    telegram_sent = False
    telegram_error = ""
    telegram_kind = ""
    if result.new_count:
        try:
            telegram_kind = send_after_import(
                store,
                imported={
                    "new_count": result.new_count,
                    "dup_count": result.dup_count,
                },
                summary=summary,
                previous=previous if previous["tx_count"] else None,
            )
            telegram_sent = bool(telegram_kind)
        except Exception as exc:  # noqa: BLE001 — surface to UI, don't crash import
            telegram_error = str(exc)

    return {
        "ok": True,
        "import": {
            "id": result.import_id,
            "filename": result.filename,
            "new_count": result.new_count,
            "dup_count": result.dup_count,
            "review_count": result.review_count,
            "period_from": result.period_from,
            "period_to": result.period_to,
        },
        "summary": summary,
        "telegram_sent": telegram_sent,
        "telegram_kind": telegram_kind,
        "telegram_error": telegram_error,
    }


@app.post("/api/pull-drive")
async def pull_drive() -> dict:
    if not _drive_on():
        raise HTTPException(status_code=400, detail="Папка Google Drive выключена")
    from .pull import month_of, pull_statements

    result = pull_statements(store, dest_dir=UPLOAD_DIR)
    newest = result.get("newest") or {}
    ym = month_of(newest.get("period_to"))
    return {
        "ok": True,
        **result,
        "year": ym[0] if ym else None,
        "month": ym[1] if ym else None,
    }


@app.get("/api/imports")
async def list_imports() -> dict:
    return {"ok": True, "imports": store.list_imports()}


@app.get("/api/summary")
async def summary(year: int | None = None, month: int | None = None) -> dict:
    date_from, date_to = _period(year, month)
    current = store.summary(date_from, date_to)
    prev_from, prev_to = store.previous_period(date_from, date_to)
    previous = store.summary(prev_from, prev_to)
    y, m = date.fromisoformat(date_from).year, date.fromisoformat(date_from).month
    digest = build_digest(
        current,
        previous if previous["tx_count"] else None,
        goal=store.get_goal(),
        stances=store.stances(),
    )
    return {
        "ok": True,
        "title": month_title(y, m),
        "year": y,
        "month": m,
        "summary": current,
        "previous": previous,
        "goal": store.get_goal(),
        "advice": digest.to_dict(),
    }


@app.get("/api/transactions")
async def transactions(
    year: int | None = None,
    month: int | None = None,
    needs_review: bool | None = None,
    limit: int = 400,
) -> dict:
    date_from = date_to = None
    if year and month:
        date_from, date_to = _period(year, month)
    rows = store.list_transactions(
        date_from=date_from,
        date_to=date_to,
        needs_review=needs_review,
        limit=min(limit, 1000),
    )
    return {"ok": True, "transactions": [public_tx(r) for r in rows]}


@app.get("/api/review")
async def review_queue() -> dict:
    rows = store.list_transactions(needs_review=True, limit=200)
    cats = store.categories()
    return {
        "ok": True,
        "count": len(rows),
        "transactions": [public_tx(r) for r in rows],
        "categories": {
            "expense": _merge_cats(DEFAULT_EXPENSE, cats.get("expense") or []),
            "income": _merge_cats(DEFAULT_INCOME, cats.get("income") or []),
        },
    }


@app.post("/api/transactions/{tx_id}/review")
async def review_one(tx_id: int, request: Request) -> dict:
    body = await request.json()
    kind = str(body.get("kind") or "expense")
    try:
        row = store.review_transaction(
            tx_id,
            kind=kind,
            user_category=str(body.get("user_category") or ""),
            user_note=str(body.get("user_note") or ""),
            is_internal=bool(body.get("is_internal")),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Операция не найдена") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    remaining = store.review_count()
    telegram_sent = False
    if remaining == 0:
        posted = str(row.get("posted_date") or date.today().isoformat())
        d = date.fromisoformat(posted[:10])
        date_from, date_to = _period(d.year, d.month)
        summary = store.summary(date_from, date_to)
        prev_from, prev_to = store.previous_period(date_from, date_to)
        previous = store.summary(prev_from, prev_to)
        try:
            telegram_sent = bool(
                send_after_review_cleared(
                    store,
                    summary=summary,
                    previous=previous if previous["tx_count"] else None,
                )
            )
        except Exception:
            telegram_sent = False
    return {
        "ok": True,
        "transaction": public_tx(row),
        "review_count": remaining,
        "telegram_sent": telegram_sent,
    }


@app.get("/api/goal")
async def get_goal() -> dict:
    return {"ok": True, "goal": store.get_goal()}


@app.post("/api/goal")
async def set_goal(request: Request) -> dict:
    body = await request.json()
    raw = body.get("amount")
    if raw in (None, ""):
        raise HTTPException(status_code=400, detail="Нужна сумма цели")
    try:
        amount = float(str(raw).replace(" ", "").replace(",", "."))
        goal = store.set_goal(amount, str(body.get("kind") or "net"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Нужна сумма цели") from exc
    return {"ok": True, "goal": goal}


@app.post("/api/notify")
async def notify(year: int | None = None, month: int | None = None) -> dict:
    if not tg.telegram_enabled():
        raise HTTPException(status_code=400, detail="Telegram не настроен")
    date_from, date_to = _period(year, month)
    summary = store.summary(date_from, date_to)
    if int(summary.get("unreviewed_count") or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail="Сначала разнесите переводы без статьи — иначе советы будут врать",
        )
    prev_from, prev_to = store.previous_period(date_from, date_to)
    previous = store.summary(prev_from, prev_to)
    send_after_review_cleared(
        store,
        summary=summary,
        previous=previous if previous["tx_count"] else None,
    )
    return {"ok": True}


def _period(year: int | None, month: int | None) -> tuple[str, str]:
    today = date.today()
    y = year or today.year
    m = month or today.month
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1).isoformat(), date(y, m, last).isoformat()


def _safe_name(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in Path(name).name)
    return keep[:80] or "statement.csv"


def _merge_cats(defaults: list[str], extra: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in [*defaults, *extra]:
        key = name.casefold()
        if key in seen or not name.strip():
            continue
        seen.add(key)
        out.append(name.strip())
    return out
