"""Simple staff auth (phone + password) with sqlite-backed accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .clients import normalize_phone

STAFF_COOKIE = "soco_staff_session"
STAFF_SESSION_TTL_SEC = int(os.getenv("TRYON_STAFF_SESSION_TTL_SEC", "43200") or "43200")


def _now_s() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + pad).encode("ascii"))


def _pbkdf2(password: str, salt: bytes, rounds: int = 120_000) -> str:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
    return f"pbkdf2_sha256${rounds}${_b64(salt)}${_b64(raw)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_b64, digest_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def _hash_password(password: str) -> str:
    return _pbkdf2(password, secrets.token_bytes(16))


@dataclass
class StaffUser:
    phone: str
    name: str
    is_active: int
    created_at: str
    updated_at: str
    last_login_at: str


class StaffAuthStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key = (
            os.getenv("TRYON_STAFF_SIGNING_KEY", "").strip() or os.getenv("TRYON_BOT_WEBHOOK_SECRET", "").strip()
        )
        if not self.signing_key:
            self.signing_key = secrets.token_hex(16)
        self._init()
        self._bootstrap_from_env()

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
                CREATE TABLE IF NOT EXISTS staff_users (
                    phone TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_staff_active ON staff_users(is_active);
                """
            )

    def _bootstrap_from_env(self) -> None:
        # Format: +79990001122:password:Имя;+79990002233:password2:Имя2
        raw = (os.getenv("TRYON_STAFF_BOOTSTRAP", "") or "").strip()
        if not raw:
            return
        for item in raw.split(";"):
            parts = [p.strip() for p in item.split(":")]
            if len(parts) < 2:
                continue
            phone = normalize_phone(parts[0])
            password = parts[1]
            name = parts[2] if len(parts) >= 3 else ""
            if len(re.sub(r"\D", "", phone)) < 10 or not password:
                continue
            self.upsert_user(phone=phone, password=password, name=name or phone)

    def upsert_user(self, *, phone: str, password: str, name: str = "") -> None:
        phone_n = normalize_phone(phone)
        now = _now_s()
        name_n = " ".join((name or "").strip().split())[:120]
        pwd_hash = _hash_password(password)
        with self._conn() as conn:
            cur = conn.execute("SELECT phone FROM staff_users WHERE phone = ?", (phone_n,))
            if cur.fetchone():
                conn.execute(
                    """
                    UPDATE staff_users
                    SET name = ?, password_hash = ?, updated_at = ?, is_active = 1
                    WHERE phone = ?
                    """,
                    (name_n or phone_n, pwd_hash, now, phone_n),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO staff_users(phone, name, password_hash, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (phone_n, name_n or phone_n, pwd_hash, now, now),
                )

    def get_user(self, phone: str) -> Optional[StaffUser]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT phone, name, is_active, created_at, updated_at, last_login_at
                FROM staff_users
                WHERE phone = ?
                """,
                (normalize_phone(phone),),
            )
            r = cur.fetchone()
        return StaffUser(**{k: r[k] for k in r.keys()}) if r else None

    def authenticate(self, phone: str, password: str) -> Optional[StaffUser]:
        phone_n = normalize_phone(phone)
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT phone, name, is_active, created_at, updated_at, last_login_at, password_hash
                FROM staff_users
                WHERE phone = ?
                """,
                (phone_n,),
            )
            row = cur.fetchone()
            if not row or int(row["is_active"] or 0) != 1:
                return None
            if not _verify_password(password, row["password_hash"]):
                return None
            now = _now_s()
            conn.execute("UPDATE staff_users SET last_login_at = ?, updated_at = ? WHERE phone = ?", (now, now, phone_n))
        return self.get_user(phone_n)

    def issue_token(self, phone: str) -> str:
        payload = {"phone": normalize_phone(phone), "exp": int(time.time()) + STAFF_SESSION_TTL_SEC}
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        body = _b64(raw)
        sig = _b64(hmac.new(self.signing_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def verify_token(self, token: str) -> Optional[StaffUser]:
        if not token or "." not in token:
            return None
        body, sig = token.split(".", 1)
        good = _b64(hmac.new(self.signing_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        try:
            payload = json.loads(_b64d(body).decode("utf-8"))
            if int(payload.get("exp") or 0) < int(time.time()):
                return None
            phone = normalize_phone(str(payload.get("phone") or ""))
            return self.get_user(phone)
        except Exception:
            return None
