"""Client CRM for try-on: stable client_id per phone, jobs kept 30 days."""

from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

PHOTO_RETENTION_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_s() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return _now()


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        return "+" + digits
    if len(digits) >= 10:
        return "+" + digits
    return digits


def _new_client_id() -> str:
    # Sales-friendly short id, e.g. SC-A7K2M9
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SC-{body}"


@dataclass
class Client:
    client_id: str
    phone: str
    name: str
    created_at: str
    updated_at: str
    consent_at: str = ""
    last_ip: str = ""


@dataclass
class TryonJob:
    job_id: str
    client_id: str
    created_at: str
    expires_at: str
    status: str = "done"
    error: str = ""


@dataclass
class JobWithClient:
    job_id: str
    client_id: str
    client_name: str
    client_phone: str
    created_at: str
    expires_at: str
    status: str
    error: str


class ClientStore:
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
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    phone TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    consent_at TEXT NOT NULL DEFAULT '',
                    last_ip TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);

                CREATE TABLE IF NOT EXISTS tryon_jobs (
                    job_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'done',
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(client_id) REFERENCES clients(client_id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_client ON tryon_jobs(client_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_expires ON tryon_jobs(expires_at);
                """
            )

    def get_by_phone(self, phone: str) -> Optional[Client]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM clients WHERE phone = ?", (phone,))
            r = cur.fetchone()
        return Client(**{k: r[k] for k in r.keys()}) if r else None

    def get(self, client_id: str) -> Optional[Client]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
            r = cur.fetchone()
        return Client(**{k: r[k] for k in r.keys()}) if r else None

    def upsert(
        self,
        *,
        phone: str,
        name: str,
        ip: str = "",
        consent: bool = True,
    ) -> Client:
        phone_n = normalize_phone(phone)
        name_n = " ".join((name or "").strip().split())
        now = _now_s()
        existing = self.get_by_phone(phone_n)
        if existing:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE clients
                    SET name = ?, updated_at = ?, consent_at = CASE WHEN ? THEN ? ELSE consent_at END,
                        last_ip = ?
                    WHERE client_id = ?
                    """,
                    (
                        name_n or existing.name,
                        now,
                        1 if consent else 0,
                        now,
                        ip or existing.last_ip,
                        existing.client_id,
                    ),
                )
            return self.get(existing.client_id)  # type: ignore[return-value]

        for _ in range(12):
            cid = _new_client_id()
            try:
                with self._conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO clients(client_id, phone, name, created_at, updated_at, consent_at, last_ip)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cid, phone_n, name_n, now, now, now if consent else "", ip or ""),
                    )
                return self.get(cid)  # type: ignore[return-value]
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("Could not allocate client_id")

    def create_job(self, *, job_id: str, client_id: str, status: str = "processing") -> TryonJob:
        created = _now()
        expires = created + timedelta(days=PHOTO_RETENTION_DAYS)
        row = TryonJob(
            job_id=job_id,
            client_id=client_id,
            created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=status,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tryon_jobs(job_id, client_id, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row.job_id, row.client_id, row.created_at, row.expires_at, row.status),
            )
        return row

    def mark_job(self, job_id: str, *, status: str, error: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE tryon_jobs SET status = ?, error = ? WHERE job_id = ?",
                (status, (error or "")[:500], job_id),
            )

    def get_job(self, job_id: str) -> Optional[TryonJob]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM tryon_jobs WHERE job_id = ?", (job_id,))
            r = cur.fetchone()
        return TryonJob(**{k: r[k] for k in r.keys()}) if r else None

    def jobs_for_client(self, client_id: str, *, include_expired: bool = False) -> list[TryonJob]:
        now = _now_s()
        with self._conn() as conn:
            if include_expired:
                cur = conn.execute(
                    "SELECT * FROM tryon_jobs WHERE client_id = ? ORDER BY created_at DESC",
                    (client_id,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT * FROM tryon_jobs
                    WHERE client_id = ? AND expires_at >= ?
                    ORDER BY created_at DESC
                    """,
                    (client_id, now),
                )
            rows = cur.fetchall()
        return [TryonJob(**{k: r[k] for k in r.keys()}) for r in rows]

    def purge_expired(self, upload_dir: Path, result_dir: Path) -> int:
        """Delete expired job folders and DB rows. Returns removed count."""
        now = _now_s()
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT job_id FROM tryon_jobs WHERE expires_at < ?",
                (now,),
            )
            job_ids = [r["job_id"] for r in cur.fetchall()]
            if job_ids:
                conn.executemany("DELETE FROM tryon_jobs WHERE job_id = ?", [(j,) for j in job_ids])
        removed = 0
        for job_id in job_ids:
            for root in (upload_dir / job_id, result_dir / job_id):
                if root.exists():
                    shutil.rmtree(root, ignore_errors=True)
                    removed += 1
        return len(job_ids)

    def recent_jobs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        search: str = "",
        include_expired: bool = False,
        status: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> list[JobWithClient]:
        limit = max(1, min(int(limit or 100), 500))
        offset = max(0, int(offset or 0))
        now = _now_s()
        q = f"%{(search or '').strip()}%"
        where = "WHERE 1=1"
        params: list[object] = []
        if not include_expired:
            where += " AND j.expires_at >= ?"
            params.append(now)
        status_n = (status or "").strip().lower()
        if status_n:
            where += " AND j.status = ?"
            params.append(status_n)
        if date_from.strip():
            where += " AND j.created_at >= ?"
            params.append(f"{date_from.strip()}T00:00:00Z")
        if date_to.strip():
            where += " AND j.created_at <= ?"
            params.append(f"{date_to.strip()}T23:59:59Z")
        if search.strip():
            where += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.client_id LIKE ? OR j.job_id LIKE ?)"
            params.extend([q, q, q, q])

        sql = f"""
            SELECT
                j.job_id,
                j.client_id,
                c.name AS client_name,
                c.phone AS client_phone,
                j.created_at,
                j.expires_at,
                j.status,
                j.error
            FROM tryon_jobs j
            JOIN clients c ON c.client_id = j.client_id
            {where}
            ORDER BY j.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._conn() as conn:
            cur = conn.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [JobWithClient(**{k: r[k] for k in r.keys()}) for r in rows]
