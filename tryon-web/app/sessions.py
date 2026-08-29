"""SQLite sessions, bot unlock, monthly phone/IP limits for try-on."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Клиентский лимит: примерок в месяц с телефона/IP. 0 = без лимита.
MONTHLY_LIMIT = max(0, int(os.getenv("TRYON_MONTHLY_LIMIT", "2") or "2"))

STATUS_PENDING_BOT = "pending_bot"
STATUS_READY = "ready"  # web consent done, no bot gate
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_ERROR = "error"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        return "+" + digits
    if len(digits) >= 10:
        return "+" + digits
    return digits


def _clean_attr(value: str, max_len: int = 255) -> str:
    return (value or "").strip()[:max_len]


@dataclass
class Session:
    token: str
    phone: str
    name: str
    channel: str
    ip: str
    created_at: str
    bot_user_id: str = ""
    bot_chat_id: str = ""
    unlocked_at: str = ""
    job_id: str = ""
    status: str = STATUS_PENDING_BOT
    error: str = ""
    # Yandex Metrika ClientID for offline conversions (1C webhook: ym_cid)
    ym_cid: str = ""
    yclid: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    utm_content: str = ""
    utm_term: str = ""
    return_url: str = ""

    @property
    def unlocked(self) -> bool:
        return bool(self.unlocked_at and self.bot_user_id)

    @property
    def generation_id(self) -> str:
        """Alias for deep-link / CRM: session token is the generation_id."""
        return self.token


def _session_from_row(r: sqlite3.Row) -> Session:
    data = {k: r[k] for k in r.keys()}
    data.setdefault("status", STATUS_PENDING_BOT)
    data.setdefault("error", "")
    for key in (
        "ym_cid",
        "yclid",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "return_url",
    ):
        data.setdefault(key, "")
    # Legacy column name from early MVP
    if not data.get("ym_cid") and data.get("yandex_client_id"):
        data["ym_cid"] = data["yandex_client_id"]
    data.pop("yandex_client_id", None)
    return Session(**{k: v for k, v in data.items() if k in Session.__dataclass_fields__})


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    phone TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    ip TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    bot_user_id TEXT NOT NULL DEFAULT '',
                    bot_chat_id TEXT NOT NULL DEFAULT '',
                    unlocked_at TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending_bot',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone);
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    month TEXT NOT NULL,
                    session_token TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_phone_month ON usage_events(phone, month);
                CREATE INDEX IF NOT EXISTS idx_usage_ip_month ON usage_events(ip, month);
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "status" not in cols:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'pending_bot'"
                )
            if "error" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN error TEXT NOT NULL DEFAULT ''")
            for col in (
                "ym_cid",
                "yclid",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "utm_content",
                "utm_term",
                "return_url",
            ):
                if col not in cols:
                    conn.execute(
                        f"ALTER TABLE sessions ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                    )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "yandex_client_id" in cols and "ym_cid" in cols:
                conn.execute(
                    """
                    UPDATE sessions
                    SET ym_cid = yandex_client_id
                    WHERE (ym_cid IS NULL OR ym_cid = '')
                      AND yandex_client_id IS NOT NULL
                      AND yandex_client_id != ''
                    """
                )

    def create(
        self,
        *,
        phone: str,
        name: str,
        channel: str,
        ip: str,
        yandex_client_id: str = "",
        ym_cid: str = "",
        yclid: str = "",
        utm_source: str = "",
        utm_medium: str = "",
        utm_campaign: str = "",
        utm_content: str = "",
        utm_term: str = "",
        return_url: str = "",
    ) -> Session:
        token = secrets.token_hex(8)
        cid = _clean_attr(ym_cid or yandex_client_id, 64)
        row = Session(
            token=token,
            phone=phone,
            name=name,
            channel=channel,
            ip=ip or "",
            created_at=_now(),
            status=STATUS_PENDING_BOT,
            ym_cid=cid,
            yclid=_clean_attr(yclid),
            utm_source=_clean_attr(utm_source),
            utm_medium=_clean_attr(utm_medium),
            utm_campaign=_clean_attr(utm_campaign),
            utm_content=_clean_attr(utm_content),
            utm_term=_clean_attr(utm_term),
            return_url=_clean_attr(return_url, 512),
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    token, phone, name, channel, ip, created_at, status,
                    ym_cid, yclid,
                    utm_source, utm_medium, utm_campaign, utm_content, utm_term,
                    return_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.token,
                    row.phone,
                    row.name,
                    row.channel,
                    row.ip,
                    row.created_at,
                    row.status,
                    row.ym_cid,
                    row.yclid,
                    row.utm_source,
                    row.utm_medium,
                    row.utm_campaign,
                    row.utm_content,
                    row.utm_term,
                    row.return_url,
                ),
            )
        return row

    def create_web_consent(
        self,
        *,
        phone: str,
        name: str,
        ip: str,
        yandex_client_id: str = "",
        ym_cid: str = "",
        yclid: str = "",
        utm_source: str = "",
        utm_medium: str = "",
        utm_campaign: str = "",
        utm_content: str = "",
        utm_term: str = "",
    ) -> Session:
        """Create session unlocked for on-site try-on (no bot verification)."""
        token = secrets.token_hex(8)
        now = _now()
        cid = _clean_attr(ym_cid or yandex_client_id, 64)
        row = Session(
            token=token,
            phone=phone,
            name=name,
            channel="web",
            ip=ip or "",
            created_at=now,
            bot_user_id="web",
            bot_chat_id="web",
            unlocked_at=now,
            status=STATUS_READY,
            ym_cid=cid,
            yclid=_clean_attr(yclid),
            utm_source=_clean_attr(utm_source),
            utm_medium=_clean_attr(utm_medium),
            utm_campaign=_clean_attr(utm_campaign),
            utm_content=_clean_attr(utm_content),
            utm_term=_clean_attr(utm_term),
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                    token, phone, name, channel, ip, created_at,
                    bot_user_id, bot_chat_id, unlocked_at, status,
                    ym_cid, yclid,
                    utm_source, utm_medium, utm_campaign, utm_content, utm_term
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.token,
                    row.phone,
                    row.name,
                    row.channel,
                    row.ip,
                    row.created_at,
                    row.bot_user_id,
                    row.bot_chat_id,
                    row.unlocked_at,
                    row.status,
                    row.ym_cid,
                    row.yclid,
                    row.utm_source,
                    row.utm_medium,
                    row.utm_campaign,
                    row.utm_content,
                    row.utm_term,
                ),
            )
        return row

    def get(self, token: str) -> Optional[Session]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,))
            r = cur.fetchone()
        if not r:
            return None
        return _session_from_row(r)

    def latest_by_bot_user(self, bot_user_id: str) -> Optional[Session]:
        """Most recent session linked to this bot user (for button callbacks)."""
        uid = str(bot_user_id or "").strip()
        if not uid:
            return None
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT * FROM sessions
                WHERE bot_user_id = ? OR bot_chat_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (uid, uid),
            )
            r = cur.fetchone()
        if not r:
            return None
        return _session_from_row(r)

    def unlock(self, token: str, *, bot_user_id: str, bot_chat_id: str = "") -> Optional[Session]:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET bot_user_id = ?, bot_chat_id = ?, unlocked_at = ?
                WHERE token = ?
                """,
                (str(bot_user_id), str(bot_chat_id or bot_user_id), _now(), token),
            )
        return self.get(token)

    def unlock_by_payload(self, payload: str, *, bot_user_id: str, bot_chat_id: str = "") -> Optional[Session]:
        token = (payload or "").strip()
        if not token or not re.fullmatch(r"[a-fA-F0-9]{8,32}", token):
            return None
        sess = self.get(token)
        if not sess:
            return None
        return self.unlock(token, bot_user_id=bot_user_id, bot_chat_id=bot_chat_id)

    def claim_processing(self, token: str) -> Optional[Session]:
        """Atomically move pending_bot/ready → processing. Returns session if claimed."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET status = ?
                WHERE token = ?
                  AND status IN (?, ?)
                  AND unlocked_at != ''
                  AND bot_user_id != ''
                """,
                (STATUS_PROCESSING, token, STATUS_PENDING_BOT, STATUS_READY),
            )
            if cur.rowcount != 1:
                return None
        return self.get(token)

    def claim_web_tryon(self, token: str) -> Optional[Session]:
        """Claim unlocked web session for on-site try-on (ready/done → processing)."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE sessions
                SET status = ?, error = ''
                WHERE token = ?
                  AND channel = 'web'
                  AND unlocked_at != ''
                  AND status IN (?, ?, ?)
                """,
                (STATUS_PROCESSING, token, STATUS_READY, STATUS_DONE, STATUS_ERROR),
            )
            if cur.rowcount != 1:
                return None
        return self.get(token)

    def set_job(self, token: str, job_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET job_id = ? WHERE token = ?", (job_id, token))

    def set_channel(self, token: str, channel: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE sessions SET channel = ? WHERE token = ?", (channel, token))

    def prepare_messenger_delivery(self, token: str, *, job_id: str) -> Optional[Session]:
        """Mark session ready for bot delivery of an already-finished job."""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET job_id = ?, status = ?, error = '', unlocked_at = '', bot_user_id = '', bot_chat_id = ''
                WHERE token = ?
                """,
                (job_id, STATUS_DONE, token),
            )
        return self.get(token)

    def mark_done(self, token: str, job_id: str = "") -> None:
        with self._conn() as conn:
            if job_id:
                conn.execute(
                    "UPDATE sessions SET status = ?, job_id = ?, error = '' WHERE token = ?",
                    (STATUS_DONE, job_id, token),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET status = ?, error = '' WHERE token = ?",
                    (STATUS_DONE, token),
                )

    def mark_error(self, token: str, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, error = ? WHERE token = ?",
                (STATUS_ERROR, (error or "")[:500], token),
            )

    def usage_count_phone(self, phone: str, month: Optional[str] = None) -> int:
        month = month or _month()
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM usage_events WHERE phone = ? AND month = ?",
                (phone, month),
            )
            return int(cur.fetchone()["c"])

    def usage_count_ip(self, ip: str, month: Optional[str] = None) -> int:
        month = month or _month()
        if not ip:
            return 0
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM usage_events WHERE ip = ? AND month = ?",
                (ip, month),
            )
            return int(cur.fetchone()["c"])

    def check_limits(self, phone: str, ip: str, limit: int = MONTHLY_LIMIT) -> tuple[bool, str]:
        if limit <= 0:
            return True, ""
        msg = (
            f"На одном устройстве доступно {limit} примерки в месяц. "
            "На консультации с мастером количество примерок не ограничено."
        )
        pc = self.usage_count_phone(phone)
        if pc >= limit:
            return False, msg
        ic = self.usage_count_ip(ip)
        if ip and ic >= limit:
            return False, msg
        return True, ""

    def record_usage(self, *, phone: str, ip: str, session_token: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO usage_events(phone, ip, month, session_token, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (phone, ip or "", _month(), session_token, _now()),
            )
