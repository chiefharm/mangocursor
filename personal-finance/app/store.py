"""SQLite ledger for imported bank operations."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .parse import ParsedTx, StatementMeta

UNLABELED_CATEGORY = "Переводы без разметки"
INCOME_CATEGORY = "Доходы"
INTERNAL_CATEGORY = "Между своими"
UNREVIEWED_CATEGORY = "Не разобрано"

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

CREATE TABLE IF NOT EXISTS statement_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    period_from TEXT,
    period_to TEXT,
    stmt_income REAL,
    stmt_expense REAL,
    stmt_unconfirmed REAL,
    stmt_opening REAL,
    stmt_closing REAL,
    from_header INTEGER NOT NULL DEFAULT 0,
    book_income REAL,
    book_expense REAL,
    book_holds REAL,
    matched INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period_from TEXT NOT NULL,
    period_to TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def tx_is_hold(tx: ParsedTx) -> bool:
    return (tx.status or "").lower() == "hold" or bool((tx.extra or {}).get("hold"))


def tx_uid(tx: ParsedTx, *, legacy: bool = False) -> str:
    extra = tx.extra or {}
    parts = [
        tx.posted_at.strftime("%Y-%m-%d %H:%M:%S"),
        f"{tx.amount:.2f}",
        tx.description,
        tx.card,
        tx.mcc,
        tx.category,
    ]
    if tx_is_hold(tx):
        parts.append("hold")
    if not legacy:
        parts.append(str(extra.get("code") or ""))
        if tx_is_hold(tx):
            parts.append(str(extra.get("raw") or "")[:80])
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_STOP_WORDS = {
    "hold",
    "online",
    "moscow",
    "moskva",
    "sankt",
    "peterbu",
    "krasnoyarsk",
    "operation",
    "операция",
    "операции",
    "неподтвержденная",
    "sber",
    "карта",
    "карте",
    "сумму",
    "дата",
    "совершения",
    "место",
    "для",
    "без",
    "ндс",
    "руб",
    "rur",
}


def _op_tokens(*parts: str) -> set[str]:
    blob = " ".join(p for p in parts if p).lower().replace("ё", "е")
    blob = blob.replace("tsum", "цум").replace("samokat", "самокат")
    blob = blob.replace("pyaterochka", "пятерочка").replace("litres", "литрес")
    words = re.findall(r"[a-zа-я]{3,}", blob)
    return {w for w in words if w not in _STOP_WORDS}


def _same_purchase(tx: ParsedTx, row: sqlite3.Row | dict[str, Any]) -> bool:
    want = _op_tokens(tx.description)
    got = _op_tokens(str(row["description"] or ""))
    return bool(want and got and want & got)


def _amount_date_clause(holds: bool) -> str:
    status = "LOWER(COALESCE(status, '')) = 'hold'"
    if not holds:
        status = "LOWER(COALESCE(status, '')) != 'hold'"
    return f"""
        abs(amount - ?) < 0.005
        AND posted_date BETWEEN ? AND ?
        AND {status}
    """


def _hold_window(posted: date) -> tuple[str, str]:
    return (posted - timedelta(days=3)).isoformat(), (posted + timedelta(days=3)).isoformat()


def _find_matching_neighbors(
    conn: sqlite3.Connection, tx: ParsedTx, *, holds: bool
) -> list[sqlite3.Row]:
    date_from, date_to = _hold_window(tx.posted_date)
    rows = conn.execute(
        f"SELECT * FROM transactions WHERE {_amount_date_clause(holds)}",
        (tx.amount, date_from, date_to),
    ).fetchall()
    return [row for row in rows if _same_purchase(tx, row)]


def _delete_matching_neighbors(conn: sqlite3.Connection, tx: ParsedTx, *, holds: bool) -> None:
    for row in _find_matching_neighbors(conn, tx, holds=holds):
        conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))


def _lookup_existing(conn: sqlite3.Connection, tx: ParsedTx) -> sqlite3.Row | None:
    for legacy in (False, True):
        row = conn.execute(
            "SELECT * FROM transactions WHERE uid = ?", (tx_uid(tx, legacy=legacy),)
        ).fetchone()
        if row:
            return row
    return None


def _refresh_existing(
    conn: sqlite3.Connection, row: sqlite3.Row, tx: ParsedTx, uid: str
) -> None:
    locked = bool((row["user_category"] or "").strip())
    extra_json = json.dumps(tx.extra or {}, ensure_ascii=False)
    in_queue = int(row["needs_review"] or 0) == 1
    kind = tx.suggested_kind if in_queue else (row["kind"] or tx.suggested_kind)
    internal = (
        (1 if tx.suggested_internal else 0)
        if in_queue
        else int(row["is_internal"] or 0)
    )
    bank_category = row["bank_category"] if locked else (tx.category or row["bank_category"])
    description = tx.description or row["description"]
    conn.execute(
        """
        UPDATE transactions SET
            uid = ?, bank_category = ?, description = ?, mcc = ?, card = ?,
            status = ?, kind = ?, is_internal = ?, extra = ?
        WHERE id = ?
        """,
        (
            uid,
            bank_category,
            description,
            tx.mcc or row["mcc"],
            tx.card or row["card"],
            tx.status,
            kind,
            internal,
            extra_json,
            row["id"],
        ),
    )


def _money_close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.051


def _write_snapshot(
    conn: sqlite3.Connection,
    *,
    filename: str,
    imported_at: str,
    period_from: str | None,
    period_to: str | None,
    meta: StatementMeta | None,
) -> dict[str, Any] | None:
    if not period_from or not period_to:
        return None
    book = conn.execute(
        """
        SELECT
            ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2) AS income,
            ROUND(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 2) AS expense,
            ROUND(SUM(CASE WHEN amount < 0 AND LOWER(COALESCE(status,'')) = 'hold'
                           THEN -amount ELSE 0 END), 2) AS holds
        FROM transactions
        WHERE posted_date >= ? AND posted_date <= ?
        """,
        (period_from, period_to),
    ).fetchone()
    book_income = float(book["income"] or 0)
    book_expense = float(book["expense"] or 0)
    book_holds = float(book["holds"] or 0)
    stmt_income = meta.income if meta else None
    stmt_expense = meta.expense if meta else None
    stmt_unconfirmed = meta.unconfirmed if meta else None
    matched = _money_close(stmt_income, book_income) and _money_close(
        stmt_expense, book_expense
    )
    conn.execute(
        """
        INSERT INTO statement_snapshots (
            filename, imported_at, period_from, period_to,
            stmt_income, stmt_expense, stmt_unconfirmed, stmt_opening, stmt_closing,
            from_header, book_income, book_expense, book_holds, matched
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            imported_at,
            period_from,
            period_to,
            stmt_income,
            stmt_expense,
            stmt_unconfirmed,
            meta.opening if meta else None,
            meta.closing if meta else None,
            1 if meta and meta.from_header else 0,
            book_income,
            book_expense,
            book_holds,
            1 if matched else 0,
        ),
    )
    return {
        "period_from": period_from,
        "period_to": period_to,
        "filename": filename,
        "from_header": bool(meta and meta.from_header),
        "stmt_income": stmt_income,
        "stmt_expense": stmt_expense,
        "stmt_unconfirmed": stmt_unconfirmed,
        "book_income": book_income,
        "book_expense": book_expense,
        "book_holds": book_holds,
        "income_ok": _money_close(stmt_income, book_income),
        "expense_ok": _money_close(stmt_expense, book_expense),
        "matched": matched,
        "income_delta": round(book_income - float(stmt_income or 0), 2)
        if stmt_income is not None
        else None,
        "expense_delta": round(book_expense - float(stmt_expense or 0), 2)
        if stmt_expense is not None
        else None,
    }


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
    refreshed_count: int = 0
    reconcile: dict[str, Any] | None = None


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

    def import_transactions(
        self,
        txs: list[ParsedTx],
        filename: str,
        meta: StatementMeta | None = None,
    ) -> ImportResult:
        now = datetime.now().isoformat(timespec="seconds")
        dates = [tx.posted_date.isoformat() for tx in txs]
        period_from = (meta.period_from if meta and meta.period_from else None) or (
            min(dates) if dates else None
        )
        period_to = (meta.period_to if meta and meta.period_to else None) or (
            max(dates) if dates else None
        )
        new_ids: list[int] = []
        new_count = 0
        dup_count = 0
        refreshed_count = 0
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
                existing = _lookup_existing(conn, tx)
                if existing:
                    _refresh_existing(conn, existing, tx, uid)
                    dup_count += 1
                    refreshed_count += 1
                    continue
                if tx_is_hold(tx) and _find_matching_neighbors(conn, tx, holds=False):
                    dup_count += 1
                    continue
                if not tx_is_hold(tx):
                    _delete_matching_neighbors(conn, tx, holds=True)
                kind = tx.suggested_kind
                is_internal = 1 if tx.suggested_internal else 0
                needs = 1 if tx.needs_review else 0
                extra_json = json.dumps(tx.extra or {}, ensure_ascii=False)
                cur = conn.execute(
                    """
                    INSERT INTO transactions (
                        uid, import_id, posted_at, posted_date, amount, currency,
                        bank_category, description, mcc, card, status, kind,
                        user_category, user_note, is_internal, needs_review, extra
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)
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
                        extra_json,
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
            reconcile = _write_snapshot(
                conn,
                filename=filename,
                imported_at=now,
                period_from=period_from,
                period_to=period_to,
                meta=meta,
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
            refreshed_count=refreshed_count,
            reconcile=reconcile,
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

    def list_ledger(
        self,
        date_from: str,
        date_to: str,
        *,
        bucket: str,
        category: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Operations that make up an income/expense total or a category bar."""
        if bucket not in {"income", "expense"}:
            raise ValueError("bucket must be income or expense")
        want = (category or "").strip()
        rows = self.list_transactions(date_from=date_from, date_to=date_to, limit=limit)
        out = []
        for row in rows:
            found, name = classify_pnl(row)
            if found != bucket:
                continue
            if want and name != want:
                continue
            out.append(row)
        return out

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
        if kind not in {"expense", "income", "transfer", "unlabeled"}:
            raise ValueError("kind must be expense, income, transfer or unlabeled")
        if kind == "unlabeled":
            internal = 0
            kind = "unlabeled"
            user_category = UNLABELED_CATEGORY
        else:
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

    def recategorize(
        self,
        tx_id: int,
        *,
        user_category: str,
        kind: str | None = None,
        user_note: str | None = None,
    ) -> dict[str, Any]:
        """Change the P&L article on an already imported operation."""
        cat = (user_category or "").strip()
        if not cat:
            raise ValueError("Укажите статью")
        row = self.get_transaction(tx_id)
        if row is None:
            raise KeyError(tx_id)
        note = (row.get("user_note") or "") if user_note is None else user_note
        chosen = (kind or "").strip()
        if chosen not in {"income", "expense", "transfer"}:
            if float(row.get("amount") or 0) > 0:
                chosen = "income"
            else:
                chosen = "expense"
        return self.review_transaction(
            tx_id,
            kind=chosen,
            user_category=cat,
            user_note=str(note or ""),
            is_internal=chosen == "transfer",
        )

    def leave_unlabeled(self, tx_id: int | None = None) -> list[dict[str, Any]]:
        """Park one or all queued transfers in «Переводы без разметки»."""
        if tx_id is not None:
            return [self.review_transaction(tx_id, kind="unlabeled")]
        pending = self.list_transactions(needs_review=True, limit=2000)
        out = []
        for row in pending:
            out.append(self.review_transaction(int(row["id"]), kind="unlabeled"))
        return out

    def accept_all_income(self) -> list[dict[str, Any]]:
        """Mark every queued inflow as income; leave outflows in the queue."""
        pending = self.list_transactions(needs_review=True, limit=2000)
        out = []
        for row in pending:
            if float(row.get("amount") or 0) <= 0:
                continue
            out.append(
                self.review_transaction(
                    int(row["id"]),
                    kind="income",
                    user_category=INCOME_CATEGORY,
                )
            )
        return out

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
            if cat and cat != UNLABELED_CATEGORY:
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
        out = summarize_rows(txs, date_from, date_to)
        snap = self.latest_snapshot(date_from, date_to)
        if snap:
            out["reconcile"] = snap
        return out

    def latest_snapshot(self, date_from: str, date_to: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM statement_snapshots
                WHERE period_from <= ? AND period_to >= ?
                ORDER BY id DESC LIMIT 1
                """,
                (date_to, date_from),
            ).fetchone()
        if not row:
            return None
        stmt_income = row["stmt_income"]
        stmt_expense = row["stmt_expense"]
        book_income = float(row["book_income"] or 0)
        book_expense = float(row["book_expense"] or 0)
        return {
            "period_from": row["period_from"],
            "period_to": row["period_to"],
            "filename": row["filename"],
            "from_header": bool(row["from_header"]),
            "stmt_income": stmt_income,
            "stmt_expense": stmt_expense,
            "stmt_unconfirmed": row["stmt_unconfirmed"],
            "book_income": book_income,
            "book_expense": book_expense,
            "book_holds": float(row["book_holds"] or 0),
            "income_ok": _money_close(stmt_income, book_income),
            "expense_ok": _money_close(stmt_expense, book_expense),
            "matched": bool(row["matched"]),
            "income_delta": round(book_income - float(stmt_income or 0), 2)
            if stmt_income is not None
            else None,
            "expense_delta": round(book_expense - float(stmt_expense or 0), 2)
            if stmt_expense is not None
            else None,
        }

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


def classify_pnl(row: dict[str, Any]) -> tuple[str | None, str]:
    """Income/expense by sign, as on the statement. Nothing is dropped from сальдо."""
    amount = float(row["amount"])
    if abs(amount) < 0.0001:
        return None, ""
    bucket = "income" if amount > 0 else "expense"
    if (row.get("kind") == "unlabeled") or (row.get("user_category") == UNLABELED_CATEGORY):
        return bucket, UNLABELED_CATEGORY
    if int(row.get("needs_review") or 0) == 1:
        return bucket, UNREVIEWED_CATEGORY
    if int(row.get("is_internal") or 0) == 1 or row.get("kind") == "transfer":
        return bucket, INTERNAL_CATEGORY
    return bucket, effective_category(row)


def summarize_rows(txs: list[dict[str, Any]], date_from: str, date_to: str) -> dict[str, Any]:
    income = 0.0
    expense = 0.0
    internal = 0.0
    unreviewed_sum = 0.0
    unreviewed_count = 0
    income_cats: dict[str, float] = {}
    expense_cats: dict[str, float] = {}
    pending: list[dict[str, Any]] = []

    unlabeled_sum = 0.0
    unlabeled: list[dict[str, Any]] = []

    for row in txs:
        amount = float(row["amount"])
        if amount > 0:
            income += amount
        elif amount < 0:
            expense += abs(amount)
        if int(row.get("needs_review") or 0) == 1:
            unreviewed_count += 1
            unreviewed_sum += amount
            pending.append(public_tx(row))
        if int(row.get("is_internal") or 0) == 1 or row.get("kind") == "transfer":
            if int(row.get("needs_review") or 0) != 1:
                internal += amount
        bucket, cat = classify_pnl(row)
        if bucket is None:
            continue
        if cat == UNLABELED_CATEGORY:
            unlabeled.append(public_tx(row))
            unlabeled_sum += amount
        if bucket == "income":
            income_cats[cat] = income_cats.get(cat, 0.0) + abs(amount)
        else:
            expense_cats[cat] = expense_cats.get(cat, 0.0) + abs(amount)

    income_bars = round(sum(income_cats.values()), 2)
    expense_bars = round(sum(expense_cats.values()), 2)
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
        "unlabeled_count": len(unlabeled),
        "unlabeled_sum": round(unlabeled_sum, 2),
        "unlabeled": unlabeled,
        "tx_count": len(txs),
        "bars_ok": _money_close(income_bars, income) and _money_close(expense_bars, expense),
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
        "status": row.get("status") or "",
        "kind": row.get("kind") or "expense",
        "user_category": row.get("user_category") or "",
        "user_note": row.get("user_note") or "",
        "is_internal": bool(row.get("is_internal")),
        "needs_review": bool(row.get("needs_review")),
        "extra": extra or {},
    }
