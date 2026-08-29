"""SQLite ledger for imported bank operations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .parse import ParsedTx

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    period_from TEXT,
    period_to TEXT,
    new_count INTEGER NOT NULL DEFAULT 0,
    dup_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    import_id INTEGER REFERENCES imports(id),
    posted_at TEXT NOT NULL,
    posted_date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'RUB',
    bank_category TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    mcc TEXT NOT NULL DEFAULT '',
    card TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'expense',
    user_category TEXT NOT NULL DEFAULT '',
    user_note TEXT NOT NULL DEFAULT '',
    is_internal INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    extra TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(posted_date);
CREATE INDEX IF NOT EXISTS idx_tx_review ON transactions(needs_review);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_stance (
    category_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    stance TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period_from TEXT NOT NULL,
    period_to TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def tx_uid(tx: ParsedTx) -> str:
    key = "|".join(
        [
            tx.posted_at.strftime("%Y-%m-%d %H:%M:%S"),
            f"{tx.amount:.2f}",
            tx.description,
            tx.card,
            tx.mcc,
            tx.category,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class ImportResult:
    import_id: int
    filename: str
    new_count: int
    dup_count: int
    review_count: int
    period_from: str | None
    period_to: str | None
    new_ids: list[int]


class FinanceStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def import_transactions(self, txs: list[ParsedTx], filename: str) -> ImportResult:
        now = datetime.now().isoformat(timespec="seconds")
        dates = [tx.posted_date.isoformat() for tx in txs]
        period_from = min(dates) if dates else None
        period_to = max(dates) if dates else None
        new_ids: list[int] = []
        new_count = 0
        dup_count = 0
        review_count = 0

        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO imports (filename, imported_at, period_from, period_to)
                VALUES (?, ?, ?, ?)
                """,
                (filename, now, period_from, period_to),
            )
            import_id = int(cur.lastrowid)
            for tx in txs:
                uid = tx_uid(tx)
                existing = conn.execute(
                    "SELECT id FROM transactions WHERE uid = ?", (uid,)
                ).fetchone()
                if existing:
                    dup_count += 1
                    continue
                kind = tx.suggested_kind
                is_internal = 1 if tx.suggested_internal else 0
                needs = 1 if tx.needs_review else 0
                cur = conn.execute(
                    """
                    INSERT INTO transactions (
                        uid, import_id, posted_at, posted_date, amount, currency,
                        bank_category, description, mcc, card, status, kind,
                        user_category, user_note, is_internal, needs_review, extra
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, '{}')
                    """,
                    (
                        uid,
                        import_id,
                        tx.posted_at.isoformat(timespec="seconds"),
                        tx.posted_date.isoformat(),
                        tx.amount,
                        tx.currency or "RUB",
                        tx.category,
                        tx.description,
                        tx.mcc,
                        tx.card,
                        tx.status,
                        kind,
                        is_internal,
                        needs,
                    ),
                )
                new_ids.append(int(cur.lastrowid))
                new_count += 1
                if needs:
                    review_count += 1
            conn.execute(
                """
                UPDATE imports
                SET new_count = ?, dup_count = ?, review_count = ?
                WHERE id = ?
                """,
                (new_count, dup_count, review_count, import_id),
            )
        return ImportResult(
            import_id=import_id,
            filename=filename,
            new_count=new_count,
            dup_count=dup_count,
            review_count=review_count,
            period_from=period_from,
            period_to=period_to,
            new_ids=new_ids,
        )

    def list_imports(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_transaction(self, tx_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (tx_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_transactions(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        needs_review: bool | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM transactions WHERE 1=1"
        args: list[Any] = []
        if date_from:
            sql += " AND posted_date >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND posted_date <= ?"
            args.append(date_to)
        if needs_review is True:
            sql += " AND needs_review = 1"
        elif needs_review is False:
            sql += " AND needs_review = 0"
        sql += " ORDER BY posted_at DESC, id DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def review_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM transactions WHERE needs_review = 1"
            ).fetchone()
        return int(row["n"] if row else 0)

    def review_transaction(
        self,
        tx_id: int,
        *,
        kind: str,
        user_category: str = "",
        user_note: str = "",
        is_internal: bool = False,
    ) -> dict[str, Any]:
        if kind not in {"expense", "income", "transfer"}:
            raise ValueError("kind must be expense, income or transfer")
        internal = 1 if is_internal or kind == "transfer" else 0
        if internal:
            kind = "transfer"
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE transactions
                SET kind = ?, user_category = ?, user_note = ?,
                    is_internal = ?, needs_review = 0
                WHERE id = ?
                """,
                (kind, user_category.strip(), user_note.strip(), internal, tx_id),
            )
            if cur.rowcount == 0:
                raise KeyError(tx_id)
        row = self.get_transaction(tx_id)
        assert row is not None
        return row

    def categories(self) -> dict[str, list[str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT kind,
                       CASE WHEN user_category != '' THEN user_category ELSE bank_category END
                         AS cat
                FROM transactions
                WHERE is_internal = 0 AND needs_review = 0
                  AND (user_category != '' OR bank_category != '')
                """
            ).fetchall()
        buckets: dict[str, set[str]] = {"expense": set(), "income": set(), "transfer": set()}
        for row in rows:
            kind = row["kind"] if row["kind"] in buckets else "expense"
            cat = (row["cat"] or "").strip()
            if cat:
                buckets[kind].add(cat)
        return {k: sorted(v, key=str.lower) for k, v in buckets.items()}

    def summary(self, date_from: str, date_to: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM transactions
                WHERE posted_date >= ? AND posted_date <= ?
                ORDER BY posted_at
                """,
                (date_from, date_to),
            ).fetchall()
        txs = [dict(r) for r in rows]
        return summarize_rows(txs, date_from, date_to)

    def previous_period(self, date_from: str, date_to: str) -> tuple[str, str]:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
        span = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return prev_start.isoformat(), prev_end.isoformat()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_goal(self) -> dict[str, Any] | None:
        raw = self.get_setting("goal_amount")
        if raw is None or raw == "":
            return None
        try:
            amount = float(raw)
        except ValueError:
            return None
        kind = self.get_setting("goal_kind", "net") or "net"
        return {"kind": kind, "amount": amount}

    def set_goal(self, amount: float, kind: str = "net") -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Цель должна быть больше нуля")
        if kind not in {"net", "expense_cap"}:
            kind = "net"
        self.set_setting("goal_amount", str(round(float(amount), 2)))
        self.set_setting("goal_kind", kind)
        goal = self.get_goal()
        assert goal is not None
        return goal

    def stances(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT category_key, stance FROM category_stance"
            ).fetchall()
        return {str(r["category_key"]): str(r["stance"]) for r in rows}

    def set_stance(self, category: str, stance: str) -> None:
        if stance not in {"normal", "cut", "not_expense"}:
            raise ValueError("unknown stance")
        name = category.strip()
        key = name.casefold()
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO category_stance (category_key, category, stance, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category_key) DO UPDATE SET
                    category = excluded.category,
                    stance = excluded.stance,
                    updated_at = excluded.updated_at
                """,
                (key, name, stance, now),
            )

    def save_digest(self, payload: dict[str, Any]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO digests (created_at, period_from, period_to, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    now,
                    payload.get("period_from") or "",
                    payload.get("period_to") or "",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def get_digest(self, digest_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM digests WHERE id = ?", (digest_id,)
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["payload"])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


def effective_category(row: dict[str, Any]) -> str:
    return (row.get("user_category") or row.get("bank_category") or "Без категории").strip()


def summarize_rows(txs: list[dict[str, Any]], date_from: str, date_to: str) -> dict[str, Any]:
    income = 0.0
    expense = 0.0
    internal = 0.0
    unreviewed_sum = 0.0
    unreviewed_count = 0
    income_cats: dict[str, float] = {}
    expense_cats: dict[str, float] = {}
    pending: list[dict[str, Any]] = []

    for row in txs:
        amount = float(row["amount"])
        if int(row.get("needs_review") or 0) == 1:
            unreviewed_count += 1
            unreviewed_sum += amount
            pending.append(public_tx(row))
            continue
        if int(row.get("is_internal") or 0) == 1 or row.get("kind") == "transfer":
            internal += amount
            continue
        cat = effective_category(row)
        if amount > 0 or row.get("kind") == "income":
            income += abs(amount)
            income_cats[cat] = income_cats.get(cat, 0.0) + abs(amount)
        else:
            expense += abs(amount)
            expense_cats[cat] = expense_cats.get(cat, 0.0) + abs(amount)

    return {
        "period": {"from": date_from, "to": date_to},
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "internal": round(internal, 2),
        "unreviewed_count": unreviewed_count,
        "unreviewed_sum": round(unreviewed_sum, 2),
        "income_by_category": _sorted_cats(income_cats),
        "expense_by_category": _sorted_cats(expense_cats),
        "unreviewed": pending,
        "tx_count": len(txs),
    }


def _sorted_cats(d: dict[str, float]) -> list[dict[str, Any]]:
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": k, "amount": round(v, 2)} for k, v in items]


def public_tx(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            extra = {}
    return {
        "id": row["id"],
        "posted_at": row["posted_at"],
        "posted_date": row["posted_date"],
        "amount": row["amount"],
        "currency": row.get("currency") or "RUB",
        "bank_category": row.get("bank_category") or "",
        "description": row.get("description") or "",
        "mcc": row.get("mcc") or "",
        "card": row.get("card") or "",
        "kind": row.get("kind") or "expense",
        "user_category": row.get("user_category") or "",
        "user_note": row.get("user_note") or "",
        "is_internal": bool(row.get("is_internal")),
        "needs_review": bool(row.get("needs_review")),
        "extra": extra or {},
    }
