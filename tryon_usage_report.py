#!/usr/bin/env python3
"""Daily PerfectCorp try-on token usage: clients vs staff -> Telegram DM.

Clients: primerka.soco-salon.ru → sessions.channel in (telegram, max)
Staff:   primerka.soco-salon.ru/staff → sessions.channel = web

Units ≈ successful result images × 2 (PerfectCorp hair-transfer SKU).

Prod data lives on NSK VPS (/opt/soco-tryon/data). Telegram send goes via
TRYON_TG_RELAY_URL (Amsterdam) because api.telegram.org is blocked from RF.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
UNITS_PER_SUCCESS = 2.0


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def b(text: str) -> str:
    return f"<b>{text}</b>"


def num(v: float | int) -> str:
    if isinstance(v, float) and not v.is_integer():
        return b(f"{v:.2f}".replace(".", ","))
    return b(f"{int(round(v)):,}".replace(",", " "))


def day_bounds_utc_iso(day: date) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day, tzinfo=MSK)
    end = start + timedelta(days=1)
    return (
        start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@dataclass
class Bucket:
    sessions: int = 0
    done: int = 0
    error: int = 0
    transfers: int = 0

    @property
    def units(self) -> float:
        return self.transfers * UNITS_PER_SUCCESS


def count_after_images(results_dir: Path, job_id: str) -> int:
    if not job_id:
        return 0
    folder = results_dir / job_id
    if not folder.is_dir():
        return 0
    names = {p.name.lower() for p in folder.glob("after_*.jpg")}
    names |= {p.name.lower() for p in folder.glob("after_*.jpeg")}
    return len(names)


def load_sessions(db: Path, day_start: str, day_end: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT token, channel, status, job_id, created_at, error
            FROM sessions
            WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at
            """,
            (day_start, day_end),
        )
        return list(cur.fetchall())
    finally:
        conn.close()


def aggregate(rows: list[sqlite3.Row], results_dir: Path) -> tuple[Bucket, Bucket]:
    clients = Bucket()
    staff = Bucket()
    for row in rows:
        channel = (row["channel"] or "").strip().lower()
        if channel == "web":
            bucket = staff
        elif channel in {"telegram", "max"}:
            bucket = clients
        else:
            continue

        bucket.sessions += 1
        status = (row["status"] or "").strip().lower()
        if status == "done":
            bucket.done += 1
        elif status == "error":
            bucket.error += 1

        job_id = (row["job_id"] or "").strip() or (row["token"] or "").strip()
        if status in {"done", "error", "processing"} or job_id:
            bucket.transfers += count_after_images(results_dir, job_id)
    return clients, staff


def fetch_pc_balance(api_key: str, timeout: int = 30) -> float | None:
    if not api_key:
        return None
    req = urllib.request.Request(
        "https://yce-api-01.makeupar.com/s2s/v1.0/client/credit",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        for key in ("credit", "remaining", "balance"):
            if key in data and isinstance(data[key], (int, float)):
                return float(data[key])
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in ("credit", "remaining", "balance", "amount"):
                if key in inner and isinstance(inner[key], (int, float)):
                    return float(inner[key])
    return None


def format_bucket(title: str, bucket: Bucket) -> list[str]:
    return [
        b(title),
        f"сессий: {num(bucket.sessions)} · успешных: {num(bucket.done)} · ошибок: {num(bucket.error)}",
        f"успешных примерок (фото): {num(bucket.transfers)}",
        f"токенов (~{UNITS_PER_SUCCESS:g}×фото): {num(bucket.units)}",
    ]


def format_report(
    *,
    day: date,
    clients: Bucket,
    staff: Bucket,
    balance: float | None,
) -> str:
    total_units = clients.units + staff.units
    total_transfers = clients.transfers + staff.transfers
    lines = [
        b("Примерки · расход токенов"),
        f"за {day.strftime('%d.%m.%Y')} (вчера)",
        "",
        *format_bucket("Клиенты (primerka.soco-salon.ru)", clients),
        "",
        *format_bucket("Мастера (/staff)", staff),
        "",
        b("Итого"),
        f"успешных примерок: {num(total_transfers)}",
        f"токенов: {num(total_units)}",
    ]
    if balance is not None:
        lines.append(f"баланс PerfectCorp сейчас: {num(balance)}")
    lines.append("")
    lines.append(
        f"<i>Оценка: {UNITS_PER_SUCCESS:g} unit за каждое успешное after_*.jpg. "
        "Оборванные задачи без файла могут не попасть в отчёт.</i>"
    )
    return "\n".join(lines)


def tg_send_html(chat_id: str, text: str) -> None:
    """Send via Amsterdam relay when set (NSK cannot reach api.telegram.org)."""
    relay = os.getenv("TRYON_TG_RELAY_URL", "").strip().rstrip("/")
    token = (
        os.getenv("TRYON_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    if relay:
        url = f"{relay}/bot/sendMessage"
        headers = {
            "Content-Type": "application/json",
            "X-Relay-Secret": os.getenv("TRYON_TG_RELAY_SECRET", "").strip() or "soco-tg-relay",
        }
    else:
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        headers = {"Content-Type": "application/json"}

    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    if '"ok":true' not in raw and '"ok": true' not in raw:
        raise RuntimeError(f"Telegram send failed: {raw[:500]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Try-on token usage daily report")
    parser.add_argument("--env", default="/opt/mango-pipeline/.env", help="Telegram chat id")
    parser.add_argument(
        "--tryon-env",
        default="/opt/soco-tryon/.env",
        help="tryon .env (relay + PerfectCorp)",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="TRYON_DATA_DIR (default from env or /opt/soco-tryon/data)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", default="", help="Report day YYYY-MM-DD (default: yesterday MSK)")
    args = parser.parse_args()

    load_dotenv(Path(args.env))
    load_dotenv(Path(args.tryon_env))

    data_dir = Path(
        args.data_dir
        or os.getenv("TRYON_DATA_DIR", "").strip()
        or "/opt/soco-tryon/data"
    )
    sessions_db = data_dir / "sessions.sqlite3"
    results_dir = data_dir / "results"
    if not sessions_db.is_file():
        raise SystemExit(f"sessions DB not found: {sessions_db}")

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        day = (datetime.now(MSK) - timedelta(days=1)).date()

    day_start, day_end = day_bounds_utc_iso(day)
    rows = load_sessions(sessions_db, day_start, day_end)
    clients, staff = aggregate(rows, results_dir)
    balance = fetch_pc_balance(os.getenv("PERFECTCORP_API_KEY", "").strip())
    msg = format_report(day=day, clients=clients, staff=staff, balance=balance)

    print(
        f"[INFO] data={data_dir} day={day} sessions={len(rows)} "
        f"client_units={clients.units} staff_units={staff.units}"
    )

    if args.dry_run:
        print(msg)
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise SystemExit("Set TELEGRAM_CHAT_ID")
    tg_send_html(chat_id, msg)
    print(f"[OK] sent {len(msg)} chars to {chat_id}")


if __name__ == "__main__":
    main()
