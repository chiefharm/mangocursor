"""SQLite ledger for imported bank operations."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .parse import ParsedTx, StatementMeta
from .mcc import category_for_mcc, is_transfer_mcc

UNLABELED_CATEGORY = "Переводы без разметки"
INCOME_CATEGORY = "Доходы"
INTERNAL_CATEGORY = "Между своими"
UNREVIEWED_CATEGORY = "Не разобрано"
CASH_IN_CATEGORY = "В наличные"
HZ_CATEGORY = "Х.з"
DEST_HZ = "hz"
DEST_DELETE = "delete"
SAVINGS_ADJUST_KIND = "savings_adjust"
ADJUST_KIND = "adjust"


def _fold_cat(name: str) -> str:
    return (name or "").strip().casefold().replace("ё", "е")


_CASH_IN_KEYS = {
    _fold_cat(CASH_IN_CATEGORY),
    _fold_cat("Наличные"),
    _fold_cat("Снятие наличных"),
}


def is_cash_in_category(name: str) -> bool:
    return _fold_cat(name) in _CASH_IN_KEYS


def cash_pnl_bucket(op: dict[str, Any]) -> str | None:
    """Cash spending can sit on an article. Statement totals stay as in the PDF."""
    kind = str(op.get("kind") or "")
    amt = float(op.get("amount") or 0)
    cat = (op.get("category") or "").strip()
    if kind == "expense" and amt < 0:
        return "expense"
    if kind in {ADJUST_KIND, SAVINGS_ADJUST_KIND} and cat:
        if amt < 0:
            return "expense"
        if amt > 0:
            return "income"
    return None

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

CREATE TABLE IF NOT EXISTS mcc_map (
    mcc TEXT PRIMARY KEY,
    user_category TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'expense',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS desc_map (
    desc_key TEXT PRIMARY KEY,
    user_category TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'expense',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_categories (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'expense',
    created_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS cash_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_date TEXT NOT NULL,
    amount REAL NOT NULL,
    kind TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    tx_id INTEGER UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cash_ops_date ON cash_ops(posted_date);

CREATE TABLE IF NOT EXISTS category_plans (
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name_key TEXT NOT NULL,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (year, month, kind, name_key)
);

CREATE TABLE IF NOT EXISTS stat_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period_from TEXT NOT NULL,
    period_to TEXT NOT NULL,
    income_categories TEXT NOT NULL DEFAULT '[]',
    expense_categories TEXT NOT NULL DEFAULT '[]',
    income_total REAL NOT NULL DEFAULT 0,
    expense_total REAL NOT NULL DEFAULT 0,
    net REAL NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}'
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


def _extra_code(row: sqlite3.Row | dict[str, Any] | ParsedTx) -> str:
    if isinstance(row, ParsedTx):
        return str((row.extra or {}).get("code") or "").strip()
    try:
        payload = json.loads(row["extra"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("code") or "").strip()


def _score_existing_match(tx: ParsedTx, row: sqlite3.Row) -> int:
    """Higher is better. Used when uid drifts after MCC/category remaps."""
    score = 0
    code = _extra_code(tx)
    if code and code == _extra_code(row):
        score += 8
    if (tx.mcc or "") and (tx.mcc or "") == (row["mcc"] or ""):
        score += 4
    if (tx.card or "") and (tx.card or "") == (row["card"] or ""):
        score += 2
    if _same_purchase(tx, row):
        score += 3
    return score


def _keeper_rank(row: sqlite3.Row) -> tuple[int, int, int, int]:
    """Prefer the row the user already sorted; then older id."""
    has_user = 1 if (row["user_category"] or "").strip() else 0
    has_note = 1 if (row["user_note"] or "").strip() else 0
    out_of_queue = 0 if int(row["needs_review"] or 0) else 1
    return (has_user, out_of_queue, has_note, -int(row["id"]))


def _day_amount_candidates(
    conn: sqlite3.Connection, tx: ParsedTx
) -> list[sqlite3.Row]:
    if tx_is_hold(tx):
        return []
    return list(
        conn.execute(
            """
            SELECT * FROM transactions
            WHERE posted_date = ?
              AND abs(amount - ?) < 0.005
              AND LOWER(COALESCE(status, '')) != 'hold'
            """,
            (tx.posted_date.isoformat(), tx.amount),
        ).fetchall()
    )


def _fuzzy_candidates(conn: sqlite3.Connection, tx: ParsedTx) -> list[sqlite3.Row]:
    candidates = _day_amount_candidates(conn, tx)
    if not candidates:
        return []
    code = _extra_code(tx)
    if code:
        by_code = [row for row in candidates if _extra_code(row) == code]
        if by_code:
            return by_code
        # Different Alfa operation codes on the same day/amount are distinct
        # (two «Копилка» transfers etc.). Never merge across codes.
        if any(_extra_code(row) for row in candidates):
            return []
    scored = [
        (_score_existing_match(tx, row), row) for row in candidates
    ]
    scored = [(score, row) for score, row in scored if score > 0]
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [row for score, row in scored if score == best]


def _lookup_existing(conn: sqlite3.Connection, tx: ParsedTx) -> sqlite3.Row | None:
    found: dict[int, sqlite3.Row] = {}
    for legacy in (False, True):
        row = conn.execute(
            "SELECT * FROM transactions WHERE uid = ?", (tx_uid(tx, legacy=legacy),)
        ).fetchone()
        if row:
            found[int(row["id"])] = row
    for row in _fuzzy_candidates(conn, tx):
        found[int(row["id"])] = row
    if not found:
        return None
    return max(found.values(), key=_keeper_rank)


def _purge_sibling_twins(
    conn: sqlite3.Connection, tx: ParsedTx, keep_id: int
) -> int:
    """Drop leftover twins of the same bank line; keep the sorted one."""
    twins = [
        row
        for row in _fuzzy_candidates(conn, tx)
        if int(row["id"]) != int(keep_id)
    ]
    for row in twins:
        conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
    return len(twins)


def _mcc_key(raw: str | None) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) >= 4:
        return digits[-4:]
    return digits


def _desc_key(raw: str | None) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip().casefold()


def _load_mcc_map(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM mcc_map").fetchall()
    return {_mcc_key(r["mcc"]): r for r in rows if _mcc_key(r["mcc"])}


def _apply_mcc_rule(
    conn: sqlite3.Connection,
    tx_id: int,
    mcc: str | None,
    mcc_map: dict[str, sqlite3.Row],
) -> bool:
    rule = mcc_map.get(_mcc_key(mcc))
    if not rule:
        return False
    conn.execute(
        """
        UPDATE transactions
        SET user_category = ?, kind = ?, needs_review = 0
        WHERE id = ? AND is_internal = 0
        """,
        (rule["user_category"], rule["kind"] or "expense", tx_id),
    )
    return True


def _load_desc_map(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM desc_map").fetchall()
    return {str(r["desc_key"]): r for r in rows if r["desc_key"]}


def _apply_desc_rule(
    conn: sqlite3.Connection,
    tx_id: int,
    description: str | None,
    amount: float,
    desc_map: dict[str, sqlite3.Row],
) -> bool:
    rule = desc_map.get(_desc_key(description))
    if not rule:
        return False
    kind = (rule["kind"] or "expense").strip()
    if kind == "income" and float(amount) <= 0:
        return False
    if kind == "expense" and float(amount) >= 0:
        return False
    conn.execute(
        """
        UPDATE transactions
        SET user_category = ?, kind = ?, needs_review = 0, is_internal = 0
        WHERE id = ?
        """,
        (rule["user_category"], kind, tx_id),
    )
    return True


def _refresh_existing(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    tx: ParsedTx,
    uid: str,
    mcc_map: dict[str, sqlite3.Row] | None = None,
    desc_map: dict[str, sqlite3.Row] | None = None,
) -> None:
    # Any user-assigned article (incl. «Переводы без разметки») is sacred —
    # a wider statement re-upload must not wipe manual sorting.
    locked = bool((row["user_category"] or "").strip())
    extra_json = json.dumps(tx.extra or {}, ensure_ascii=False)
    in_queue = int(row["needs_review"] or 0) == 1
    already_sorted = not in_queue
    kind = tx.suggested_kind if in_queue else (row["kind"] or tx.suggested_kind)
    internal = (
        (1 if tx.suggested_internal else 0)
        if in_queue
        else int(row["is_internal"] or 0)
    )
    # Bank article may improve on re-import (MCC remap); that is not user sorting.
    bank_category = (tx.category or "").strip() or (row["bank_category"] or "")
    # Keep the user's description if they locked the row; otherwise refresh merchant text.
    description = (row["description"] if locked else (tx.description or row["description"]))
    # On re-import, leave the queue when the bank line now has a real article
    # (e.g. MCC mapped after a code table update). Never re-queue a sorted row.
    clear_queue = (
        in_queue
        and not locked
        and not tx.needs_review
        and not tx.suggested_internal
    )
    if locked or already_sorted:
        needs_review = 0 if already_sorted else int(row["needs_review"] or 0)
        if locked:
            # Keep the user's kind / internal / review flags exactly.
            kind = row["kind"] or kind
            internal = int(row["is_internal"] or 0)
            needs_review = int(row["needs_review"] or 0)
    elif clear_queue:
        kind = tx.suggested_kind
        internal = 0
        needs_review = 0
    else:
        needs_review = int(row["needs_review"] or 0)
    # Hard guard: never put a sorted operation back into the queue.
    if already_sorted:
        needs_review = 0
    conn.execute(
        """
        UPDATE transactions SET
            uid = ?, bank_category = ?, description = ?, mcc = ?, card = ?,
            status = ?, kind = ?, is_internal = ?, needs_review = ?, extra = ?,
            user_category = ?, user_note = ?
        WHERE id = ?
        """,
        (
            uid,
            bank_category,
            description,
            tx.mcc or row["mcc"],
            tx.card or row["card"],
            tx.status if not locked else (row["status"] or tx.status),
            kind,
            internal,
            needs_review,
            extra_json,
            row["user_category"] or "",
            row["user_note"] or "",
            row["id"],
        ),
    )
    if not locked:
        if not internal:
            _apply_mcc_rule(conn, int(row["id"]), tx.mcc or row["mcc"], mcc_map or {})
        _apply_desc_rule(
            conn,
            int(row["id"]),
            description,
            tx.amount,
            desc_map or {},
        )


def _auto_release_mcc_purchases(conn: sqlite3.Connection) -> int:
    """Move queued card purchases with a trade-point MCC into expense/income articles."""
    rows = conn.execute(
        """
        SELECT id, mcc, amount, bank_category
        FROM transactions
        WHERE needs_review = 1 AND TRIM(COALESCE(mcc, '')) != ''
        """
    ).fetchall()
    freed = 0
    for row in rows:
        mcc = row["mcc"]
        if is_transfer_mcc(mcc):
            continue
        cat = (row["bank_category"] or "").strip() or category_for_mcc(mcc, fallback="Прочее")
        if not cat or cat == "Переводы":
            continue
        kind = "expense" if float(row["amount"] or 0) < 0 else "income"
        conn.execute(
            """
            UPDATE transactions
            SET bank_category = ?, kind = ?, needs_review = 0, is_internal = 0
            WHERE id = ?
            """,
            (cat, kind, row["id"]),
        )
        freed += 1
    return freed


def _book_totals(
    conn: sqlite3.Connection, period_from: str, period_to: str
) -> tuple[float, float, float]:
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
    return (
        float(book["income"] or 0),
        float(book["expense"] or 0),
        float(book["holds"] or 0),
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
    book_income, book_expense, book_holds = _book_totals(conn, period_from, period_to)
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
            mcc_map = _load_mcc_map(conn)
            desc_map = _load_desc_map(conn)
            for tx in txs:
                uid = tx_uid(tx)
                existing = _lookup_existing(conn, tx)
                if existing:
                    _refresh_existing(
                        conn, existing, tx, uid, mcc_map=mcc_map, desc_map=desc_map
                    )
                    _purge_sibling_twins(conn, tx, int(existing["id"]))
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
                applied = False
                if not is_internal:
                    applied = _apply_mcc_rule(conn, int(cur.lastrowid), tx.mcc, mcc_map)
                applied = (
                    _apply_desc_rule(
                        conn, int(cur.lastrowid), tx.description, tx.amount, desc_map
                    )
                    or applied
                )
                if applied:
                    needs = 0
                new_count += 1
                if needs:
                    review_count += 1
            released = _auto_release_mcc_purchases(conn)
            if released:
                # Re-count queue after freeing MCC purchases stuck from older imports.
                review_count = int(
                    conn.execute(
                        "SELECT COUNT(*) AS n FROM transactions WHERE needs_review = 1"
                    ).fetchone()["n"]
                )
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
        out: list[dict[str, Any]] = []
        for row in rows:
            found, name = classify_pnl(row)
            if found is None:
                continue
            if want:
                if name != want:
                    continue
            elif found != bucket:
                continue
            out.append(row)
        for op in self.list_cash_ops(date_from, date_to):
            found = cash_pnl_bucket(op)
            if found is None:
                continue
            if want:
                name = (op.get("category") or "").strip()
                if name != want or found != bucket:
                    continue
            elif found != bucket:
                continue
            out.append(public_cash_op(op))
        out.sort(
            key=lambda r: (
                str(r.get("posted_at") or r.get("posted_date") or ""),
                str(r.get("id") or ""),
            ),
            reverse=True,
        )
        return out[: max(1, int(limit))]

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
            else:
                existing = self.get_transaction(tx_id)
                amount = float((existing or {}).get("amount") or 0)
                if amount > 0 and kind == "expense":
                    kind = "income"
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
        self._sync_cash_from_review(row)
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
        if float(row.get("amount") or 0) > 0 and chosen == "expense":
            chosen = "income"
        if chosen != "transfer":
            self.ensure_user_category(cat, chosen)
        return self.review_transaction(
            tx_id,
            kind=chosen,
            user_category=cat,
            user_note=str(note or ""),
            is_internal=chosen == "transfer",
        )

    def ensure_user_category(self, name: str, kind: str = "expense") -> str:
        cat = (name or "").strip()
        if not cat:
            raise ValueError("Укажите статью")
        bucket = kind if kind in {"expense", "income", "transfer"} else "expense"
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_categories (name, kind, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET kind = excluded.kind
                """,
                (cat, bucket, now),
            )
        return cat

    def rename_category(self, old_name: str, new_name: str, kind: str | None = None) -> dict[str, Any]:
        old = (old_name or "").strip()
        new = (new_name or "").strip()
        if not old or not new:
            raise ValueError("Нужны старое и новое название")
        if old == INTERNAL_CATEGORY or new == INTERNAL_CATEGORY:
            raise ValueError("Статью «Между своими» лучше не переименовывать")
        bucket = kind if kind in {"expense", "income", "transfer"} else None
        self.ensure_user_category(new, bucket or "expense")
        old_key = _fold_cat(old)
        new_key = _fold_cat(new)
        with self.connect() as conn:
            if old != new:
                conn.execute("DELETE FROM user_categories WHERE name = ?", (old,))
            sql = """
                UPDATE transactions
                SET user_category = ?
                WHERE is_internal = 0
                  AND TRIM(CASE WHEN user_category != '' THEN user_category ELSE bank_category END) = ?
                """
            args: list[Any] = [new, old]
            if bucket == "income":
                sql += " AND amount > 0"
            elif bucket == "expense":
                sql += " AND amount < 0"
            cur = conn.execute(sql, args)
            renamed = int(cur.rowcount)
            conn.execute(
                "UPDATE transactions SET bank_category = ? WHERE TRIM(bank_category) = ?",
                (new, old),
            )
            cash_cur = conn.execute(
                "UPDATE cash_ops SET category = ? WHERE TRIM(category) = ?",
                (new, old),
            )
            renamed += int(cash_cur.rowcount)
            conn.execute(
                "UPDATE mcc_map SET user_category = ? WHERE user_category = ?",
                (new, old),
            )
            conn.execute(
                "UPDATE desc_map SET user_category = ? WHERE user_category = ?",
                (new, old),
            )
            if old_key != new_key:
                plan_rows = conn.execute(
                    "SELECT year, month, kind, amount FROM category_plans WHERE name_key = ?",
                    (old_key,),
                ).fetchall()
                for plan in plan_rows:
                    existing = conn.execute(
                        """
                        SELECT amount FROM category_plans
                        WHERE year = ? AND month = ? AND kind = ? AND name_key = ?
                        """,
                        (plan["year"], plan["month"], plan["kind"], new_key),
                    ).fetchone()
                    if existing:
                        conn.execute(
                            """
                            UPDATE category_plans
                            SET amount = ?, name = ?
                            WHERE year = ? AND month = ? AND kind = ? AND name_key = ?
                            """,
                            (
                                round(float(existing["amount"] or 0) + float(plan["amount"] or 0), 2),
                                new,
                                plan["year"],
                                plan["month"],
                                plan["kind"],
                                new_key,
                            ),
                        )
                        conn.execute(
                            """
                            DELETE FROM category_plans
                            WHERE year = ? AND month = ? AND kind = ? AND name_key = ?
                            """,
                            (plan["year"], plan["month"], plan["kind"], old_key),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE category_plans
                            SET name_key = ?, name = ?
                            WHERE year = ? AND month = ? AND kind = ? AND name_key = ?
                            """,
                            (new_key, new, plan["year"], plan["month"], plan["kind"], old_key),
                        )
                stance = conn.execute(
                    "SELECT stance, category FROM category_stance WHERE category_key = ?",
                    (old_key,),
                ).fetchone()
                if stance:
                    conn.execute(
                        """
                        INSERT INTO category_stance (category_key, category, stance, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(category_key) DO UPDATE SET
                            category = excluded.category,
                            stance = excluded.stance,
                            updated_at = excluded.updated_at
                        """,
                        (
                            new_key,
                            new,
                            stance["stance"],
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    conn.execute(
                        "DELETE FROM category_stance WHERE category_key = ?",
                        (old_key,),
                    )
                for row in conn.execute(
                    "SELECT key, value FROM settings WHERE key LIKE 'focus_expenses:%'"
                ).fetchall():
                    try:
                        names = json.loads(row["value"] or "[]")
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(names, list):
                        continue
                    if not any(_fold_cat(str(n)) == old_key for n in names):
                        continue
                    merged: list[str] = []
                    seen: set[str] = set()
                    for name in names:
                        label = new if _fold_cat(str(name)) == old_key else str(name).strip()
                        key = _fold_cat(label)
                        if not label or key in seen:
                            continue
                        seen.add(key)
                        merged.append(label)
                    conn.execute(
                        "UPDATE settings SET value = ? WHERE key = ?",
                        (json.dumps(merged, ensure_ascii=False), row["key"]),
                    )
        return {"old_name": old, "new_name": new, "count": renamed}

    def apply_mcc(
        self,
        tx_id: int,
        *,
        user_category: str,
        kind: str | None = None,
    ) -> dict[str, Any]:
        row = self.get_transaction(tx_id)
        if row is None:
            raise KeyError(tx_id)
        mcc = _mcc_key(str(row.get("mcc") or ""))
        if not mcc:
            raise ValueError("У этой операции нет MCC — отнести по коду нельзя")
        updated = self.recategorize(tx_id, user_category=user_category, kind=kind)
        chosen = (updated.get("kind") or "expense").strip()
        if chosen not in {"income", "expense"}:
            chosen = "expense" if float(row.get("amount") or 0) < 0 else "income"
        self.ensure_user_category(user_category, chosen)
        now = datetime.now().isoformat(timespec="seconds")
        sign_sql = "amount < 0" if float(row.get("amount") or 0) < 0 else "amount > 0"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mcc_map (mcc, user_category, kind, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mcc) DO UPDATE SET
                    user_category = excluded.user_category,
                    kind = excluded.kind,
                    updated_at = excluded.updated_at
                """,
                (mcc, user_category.strip(), chosen, now),
            )
            cur = conn.execute(
                """
                UPDATE transactions
                SET user_category = ?, kind = ?, needs_review = 0, is_internal = 0
                WHERE substr('0000' || replace(replace(COALESCE(mcc,''), '*', ''), ' ', ''), -4) = ?
                  AND is_internal = 0
                  AND """
                + sign_sql,
                (user_category.strip(), chosen, mcc),
            )
            count = int(cur.rowcount)
        return {
            "mcc": mcc,
            "user_category": user_category.strip(),
            "kind": chosen,
            "count": count,
            "transaction": public_tx(self.get_transaction(tx_id) or updated),
        }

    def apply_description(
        self,
        tx_id: int,
        *,
        user_category: str,
        kind: str | None = None,
    ) -> dict[str, Any]:
        row = self.get_transaction(tx_id)
        if row is None:
            raise KeyError(tx_id)
        key = _desc_key(str(row.get("description") or ""))
        if not key:
            raise ValueError("У этой операции нет описания — отнести по тексту нельзя")
        chosen = (kind or "").strip()
        if chosen == "transfer":
            raise ValueError("По описанию можно отнести только расход или доход")
        updated = self.recategorize(tx_id, user_category=user_category, kind=kind)
        chosen = (updated.get("kind") or "expense").strip()
        if chosen not in {"income", "expense"}:
            chosen = "expense" if float(row.get("amount") or 0) < 0 else "income"
        self.ensure_user_category(user_category, chosen)
        now = datetime.now().isoformat(timespec="seconds")
        amount = float(row.get("amount") or 0)
        want_outflow = amount < 0
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO desc_map (desc_key, user_category, kind, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(desc_key) DO UPDATE SET
                    user_category = excluded.user_category,
                    kind = excluded.kind,
                    updated_at = excluded.updated_at
                """,
                (key, user_category.strip(), chosen, now),
            )
            peers = conn.execute(
                "SELECT id, description, amount FROM transactions"
            ).fetchall()
            ids = [
                int(peer["id"])
                for peer in peers
                if _desc_key(peer["description"]) == key
                and (float(peer["amount"] or 0) < 0) == want_outflow
            ]
            count = 0
            if ids:
                placeholders = ",".join("?" * len(ids))
                cur = conn.execute(
                    f"""
                    UPDATE transactions
                    SET user_category = ?, kind = ?, needs_review = 0, is_internal = 0
                    WHERE id IN ({placeholders})
                    """,
                    [user_category.strip(), chosen, *ids],
                )
                count = int(cur.rowcount)
        return {
            "description": str(row.get("description") or "").strip(),
            "user_category": user_category.strip(),
            "kind": chosen,
            "count": count,
            "transaction": public_tx(self.get_transaction(tx_id) or updated),
        }

    def find_duplicate_groups(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """Groups of likely twin rows for the same bank line (for audit / clean stats)."""
        rows = self.list_transactions(
            date_from=date_from, date_to=date_to, limit=10000
        )
        buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            if (row.get("status") or "").lower() == "hold":
                continue
            code = _extra_code(row)
            amount_key = round(float(row.get("amount") or 0), 2)
            if code:
                key: tuple[Any, ...] = (
                    row.get("posted_date") or "",
                    amount_key,
                    "code",
                    code,
                )
            else:
                key = (
                    row.get("posted_date") or "",
                    amount_key,
                    "bare",
                    (row.get("mcc") or "").strip(),
                    (row.get("card") or "").strip(),
                    _desc_key(row.get("description")),
                )
            buckets.setdefault(key, []).append(row)
        groups: list[dict[str, Any]] = []
        for key, items in buckets.items():
            if len(items) < 2:
                continue
            sorted_items = sorted(items, key=lambda r: int(r.get("id") or 0))
            keeper = max(sorted_items, key=_keeper_rank)
            extras = [r for r in sorted_items if int(r["id"]) != int(keeper["id"])]
            groups.append(
                {
                    "posted_date": sorted_items[0].get("posted_date"),
                    "amount": float(sorted_items[0].get("amount") or 0),
                    "code": _extra_code(sorted_items[0]) or None,
                    "description": sorted_items[0].get("description") or "",
                    "count": len(sorted_items),
                    "extra_count": len(extras),
                    "keeper_id": int(keeper["id"]),
                    "keeper_category": effective_category(keeper),
                    "rows": [public_tx(r) for r in sorted_items],
                }
            )
        groups.sort(key=lambda g: (g["posted_date"] or "", abs(float(g["amount"]))))
        return groups

    def collapse_duplicates(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Delete twin rows for the period; keep the already-sorted one in each group."""
        groups = self.find_duplicate_groups(date_from, date_to)
        deleted_ids: list[int] = []
        kept: list[dict[str, Any]] = []
        with self.connect() as conn:
            for g in groups:
                keeper_id = int(g["keeper_id"])
                for row in g.get("rows") or []:
                    rid = int(row["id"])
                    if rid == keeper_id:
                        continue
                    conn.execute("DELETE FROM transactions WHERE id = ?", (rid,))
                    deleted_ids.append(rid)
                kept.append(
                    {
                        "keeper_id": keeper_id,
                        "posted_date": g.get("posted_date"),
                        "amount": g.get("amount"),
                        "description": g.get("description"),
                        "keeper_category": g.get("keeper_category"),
                        "removed": int(g.get("extra_count") or 0),
                    }
                )
        return {
            "period_from": date_from,
            "period_to": date_to,
            "group_count": len(groups),
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids,
            "kept": kept,
        }

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
        with self.connect() as conn:
            saved = conn.execute("SELECT name, kind FROM user_categories").fetchall()
        for row in saved:
            kind = row["kind"] if row["kind"] in buckets else "expense"
            name = (row["name"] or "").strip()
            if name and name != UNLABELED_CATEGORY:
                buckets[kind].add(name)
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
        cash_rows = self.list_cash_ops(date_from, date_to)
        exp_cats = {c["name"]: float(c["amount"]) for c in out["expense_by_category"]}
        inc_cats = {c["name"]: float(c["amount"]) for c in out["income_by_category"]}
        for op in cash_rows:
            bucket = cash_pnl_bucket(op)
            if not bucket:
                continue
            amt = abs(float(op.get("amount") or 0))
            name = (op.get("category") or HZ_CATEGORY).strip() or HZ_CATEGORY
            if bucket == "expense":
                exp_cats[name] = exp_cats.get(name, 0.0) + amt
            else:
                inc_cats[name] = inc_cats.get(name, 0.0) + amt
        out["expense_by_category"] = _sorted_cats(exp_cats)
        out["income_by_category"] = _sorted_cats(inc_cats)
        out["wallets"] = self.wallets(date_from, date_to)
        out["cash_ops"] = [public_cash_op(op) for op in cash_rows]
        start = date.fromisoformat(date_from)
        out["plans"] = self.effective_plans(start.year, start.month)
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
            period_from = row["period_from"]
            period_to = row["period_to"]
            if period_from and period_to:
                book_income, book_expense, book_holds = _book_totals(
                    conn, period_from, period_to
                )
            else:
                book_income = float(row["book_income"] or 0)
                book_expense = float(row["book_expense"] or 0)
                book_holds = float(row["book_holds"] or 0)
        stmt_income = row["stmt_income"]
        stmt_expense = row["stmt_expense"]
        matched = _money_close(stmt_income, book_income) and _money_close(
            stmt_expense, book_expense
        )
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

    def list_plans(self, year: int, month: int) -> dict[str, dict[str, float]]:
        buckets: dict[str, dict[str, float]] = {"expense": {}, "income": {}}
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT kind, name, amount
                FROM category_plans
                WHERE year = ? AND month = ?
                """,
                (int(year), int(month)),
            ).fetchall()
        for row in rows:
            kind = row["kind"] if row["kind"] in buckets else "expense"
            name = str(row["name"] or "").strip()
            amt = round(float(row["amount"] or 0), 2)
            if name and amt > 0:
                buckets[kind][name] = amt
        return buckets

    def effective_plans(self, year: int, month: int) -> dict[str, dict[str, float]]:
        """Expense budgets carry forward until a later month sets its own."""
        own = self.list_plans(year, month)
        y, m = int(year), int(month)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT year, month, name, amount
                FROM category_plans
                WHERE kind = 'expense'
                  AND (year < ? OR (year = ? AND month <= ?))
                ORDER BY year, month, name
                """,
                (y, y, m),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[_fold_cat(str(row["name"] or ""))] = row
        expense: dict[str, float] = {}
        for row in latest.values():
            name = str(row["name"] or "").strip()
            amt = round(float(row["amount"] or 0), 2)
            if name and amt > 0:
                expense[name] = amt
        return {"expense": expense, "income": own["income"]}

    def set_plan(
        self,
        year: int,
        month: int,
        *,
        kind: str,
        name: str,
        amount: float | None,
    ) -> dict[str, Any]:
        bucket = (kind or "").strip()
        if bucket not in {"expense", "income"}:
            raise ValueError("План только для расхода или дохода")
        cat = (name or "").strip()
        if not cat:
            raise ValueError("Укажите статью")
        y, m = int(year), int(month)
        if y < 2000 or m < 1 or m > 12:
            raise ValueError("Нужен месяц")
        key = _fold_cat(cat)
        raw = 0.0 if amount is None else round(float(amount), 2)
        if raw < 0:
            raise ValueError("План не может быть меньше нуля")
        with self.connect() as conn:
            if raw < 0.0001 and bucket != "expense":
                conn.execute(
                    """
                    DELETE FROM category_plans
                    WHERE year = ? AND month = ? AND kind = ? AND name_key = ?
                    """,
                    (y, m, bucket, key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO category_plans (year, month, kind, name_key, name, amount)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(year, month, kind, name_key) DO UPDATE SET
                        name = excluded.name,
                        amount = excluded.amount
                    """,
                    (y, m, bucket, key, cat, raw),
                )
        return {
            "year": y,
            "month": m,
            "kind": bucket,
            "name": cat,
            "amount": raw,
            "plans": self.effective_plans(y, m),
        }

    def get_savings(self) -> float:
        raw = self.get_setting("savings_on_card")
        if raw in (None, ""):
            return 0.0
        try:
            return round(float(raw), 2)
        except ValueError:
            return 0.0

    def cash_balance(self, date_to: str) -> float:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT ROUND(SUM(amount), 2) AS n FROM cash_ops
                WHERE posted_date <= ? AND kind != ?
                """,
                (date_to, SAVINGS_ADJUST_KIND),
            ).fetchone()
        return float(row["n"] or 0)

    def get_cash_op(self, cash_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM cash_ops WHERE id = ?", (cash_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_cash_ops(self, date_from: str, date_to: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cash_ops
                WHERE posted_date >= ? AND posted_date <= ?
                ORDER BY posted_date DESC, id DESC
                """,
                (date_from, date_to),
            ).fetchall()
        return [dict(r) for r in rows]

    def wallets(self, date_from: str, date_to: str) -> dict[str, Any]:
        return {
            "card": self.card_balance(date_from, date_to),
            "cash": {"amount": round(self.cash_balance(date_to), 2), "as_of": date_to},
            "savings": {"amount": self.get_savings()},
        }

    def card_balance(self, date_from: str, date_to: str) -> dict[str, Any]:
        with self.connect() as conn:
            closing = conn.execute(
                """
                SELECT * FROM statement_snapshots
                WHERE stmt_closing IS NOT NULL AND period_to <= ?
                ORDER BY period_to DESC, id DESC
                LIMIT 1
                """,
                (date_to,),
            ).fetchone()
            overlap = conn.execute(
                """
                SELECT * FROM statement_snapshots
                WHERE period_from <= ? AND period_to >= ?
                ORDER BY id DESC LIMIT 1
                """,
                (date_to, date_from),
            ).fetchone()
        snap = dict(closing) if closing else None
        if overlap is not None and overlap["stmt_closing"] is not None:
            ov = dict(overlap)
            if snap is None or str(ov.get("period_to") or "") >= str(snap.get("period_to") or ""):
                snap = ov
        if snap is not None and snap.get("stmt_closing") is not None:
            base = float(snap["stmt_closing"])
            later = self._bank_sum_between(str(snap["period_to"]), date_to, after=True)
            return {"amount": round(base + later, 2), "as_of": date_to}
        month_net = self._bank_sum_between(date_from, date_to, after=False)
        return {"amount": round(month_net, 2), "as_of": date_to}

    def _bank_sum_between(self, date_from: str, date_to: str, *, after: bool) -> float:
        op = ">" if after else ">="
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT ROUND(SUM(amount), 2) AS n
                FROM transactions
                WHERE posted_date {op} ? AND posted_date <= ?
                """,
                (date_from, date_to),
            ).fetchone()
        return float(row["n"] or 0)

    def _insert_cash_op(
        self,
        *,
        posted_date: str,
        amount: float,
        kind: str,
        category: str = "",
        note: str = "",
        tx_id: int | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO cash_ops (
                    posted_date, amount, kind, category, note, tx_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (posted_date, round(float(amount), 2), kind, category, note, tx_id, now),
            )
            new_id = int(cur.lastrowid)
        row = self.get_cash_op(new_id)
        assert row is not None
        return row

    def _sync_cash_from_review(self, row: dict[str, Any]) -> None:
        tx_id = int(row["id"])
        internal = int(row.get("is_internal") or 0) == 1 or row.get("kind") == "transfer"
        is_cash = internal and is_cash_in_category(str(row.get("user_category") or ""))
        if not is_cash:
            with self.connect() as conn:
                conn.execute("DELETE FROM cash_ops WHERE tx_id = ?", (tx_id,))
            return
        amount = float(row["amount"])
        cash_amt = round(abs(amount) if amount < 0 else -abs(amount), 2)
        posted = str(row.get("posted_date") or date.today().isoformat())[:10]
        note = str(row.get("user_note") or "")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM cash_ops WHERE tx_id = ?", (tx_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE cash_ops
                    SET posted_date = ?, amount = ?, kind = ?, category = ?, note = ?
                    WHERE tx_id = ?
                    """,
                    (posted, cash_amt, "from_card", CASH_IN_CATEGORY, note, tx_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO cash_ops (
                        posted_date, amount, kind, category, note, tx_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (posted, cash_amt, "from_card", CASH_IN_CATEGORY, note, tx_id, now),
                )

    def add_cash_from_card(
        self, amount: float, posted_date: str, note: str = ""
    ) -> dict[str, Any]:
        x = abs(float(amount))
        if x < 0.0001:
            raise ValueError("Нужна сумма")
        day = date.fromisoformat(str(posted_date)[:10]).isoformat()
        text = (note or "").strip()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM transactions t
                WHERE t.posted_date = ?
                  AND t.id NOT IN (SELECT tx_id FROM cash_ops WHERE tx_id IS NOT NULL)
                """,
                (day,),
            ).fetchall()
        for row in rows:
            if _money_close(float(row["amount"]), -x):
                self.review_transaction(
                    int(row["id"]),
                    kind="transfer",
                    user_category=CASH_IN_CATEGORY,
                    user_note=text,
                    is_internal=True,
                )
                with self.connect() as conn:
                    linked = conn.execute(
                        "SELECT * FROM cash_ops WHERE tx_id = ?", (int(row["id"]),)
                    ).fetchone()
                if linked:
                    return public_cash_op(dict(linked))
        raw = self._insert_cash_op(
            posted_date=day,
            amount=x,
            kind="from_card",
            category=CASH_IN_CATEGORY,
            note=text,
            tx_id=None,
        )
        return public_cash_op(raw)

    def add_cash_expense(
        self, amount: float, category: str, posted_date: str, note: str = ""
    ) -> dict[str, Any]:
        x = abs(float(amount))
        if x < 0.0001:
            raise ValueError("Нужна сумма")
        cat = (category or "").strip()
        if not cat:
            raise ValueError("Укажите статью")
        day = date.fromisoformat(str(posted_date)[:10]).isoformat()
        self.ensure_user_category(cat, "expense")
        raw = self._insert_cash_op(
            posted_date=day,
            amount=-x,
            kind="expense",
            category=cat,
            note=(note or "").strip(),
            tx_id=None,
        )
        return public_cash_op(raw)

    def delete_cash_op(self, cash_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM cash_ops WHERE id = ?", (cash_id,))
            return cur.rowcount > 0

    def update_cash_op(
        self,
        cash_id: int,
        *,
        amount: float,
        category: str,
        posted_date: str,
        note: str = "",
    ) -> dict[str, Any]:
        row = self.get_cash_op(cash_id)
        if row is None:
            raise KeyError(cash_id)
        kind = str(row.get("kind") or "")
        if kind not in {"expense", "from_card"}:
            raise ValueError("Дату можно менять у дохода и расхода наличными")
        x = abs(float(amount))
        if x < 0.0001:
            raise ValueError("Нужна сумма")
        day = date.fromisoformat(str(posted_date)[:10]).isoformat()
        text = (note or "").strip()
        if kind == "expense":
            cat = (category or "").strip()
            if not cat:
                raise ValueError("Укажите статью")
            signed = -x
            self.ensure_user_category(cat, "expense")
        else:
            cat = CASH_IN_CATEGORY
            signed = x
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE cash_ops
                SET posted_date = ?, amount = ?, category = ?, note = ?
                WHERE id = ?
                """,
                (day, signed, cat, text, cash_id),
            )
        saved = self.get_cash_op(cash_id)
        assert saved is not None
        return public_cash_op(saved)

    def set_cash_amount(self, amount: float, dest: str, posted_date: str | None = None) -> dict[str, Any]:
        new = round(float(amount), 2)
        if dest not in {DEST_HZ, DEST_DELETE}:
            raise ValueError("Куда деть разницу: hz или delete")
        day = date.fromisoformat(str(posted_date or date.today().isoformat())[:10]).isoformat()
        old = self.cash_balance(day)
        delta = round(new - old, 2)
        if abs(delta) < 0.0001:
            return {"amount": old, "op": None}
        if dest == DEST_HZ:
            self.ensure_user_category(HZ_CATEGORY, "expense" if delta < 0 else "income")
            if delta < 0:
                op = self.add_cash_expense(abs(delta), HZ_CATEGORY, day)
            else:
                op = public_cash_op(
                    self._insert_cash_op(
                        posted_date=day,
                        amount=delta,
                        kind=ADJUST_KIND,
                        category=HZ_CATEGORY,
                        note="",
                        tx_id=None,
                    )
                )
        else:
            op = public_cash_op(
                self._insert_cash_op(
                    posted_date=day,
                    amount=delta,
                    kind=ADJUST_KIND,
                    category="",
                    note="",
                    tx_id=None,
                )
            )
        return {"amount": round(self.cash_balance(day), 2), "op": op}

    def compute_stat(
        self,
        date_from: str,
        date_to: str,
        income_categories: list[str] | None = None,
        expense_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        income_names = _clean_cat_list(income_categories)
        expense_names = _clean_cat_list(expense_categories)
        summary = self.summary(date_from, date_to)
        income_parts = _named_parts(summary.get("income_by_category") or [], income_names)
        expense_parts = _named_parts(summary.get("expense_by_category") or [], expense_names)
        income_total = round(sum(p["amount"] for p in income_parts), 2)
        expense_total = round(sum(p["amount"] for p in expense_parts), 2)
        return {
            "period_from": date_from,
            "period_to": date_to,
            "income_categories": income_names,
            "expense_categories": expense_names,
            "income_parts": income_parts,
            "expense_parts": expense_parts,
            "income": income_total,
            "expense": expense_total,
            "net": round(income_total - expense_total, 2),
        }

    def save_stat_snapshot(
        self,
        date_from: str,
        date_to: str,
        income_categories: list[str] | None = None,
        expense_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        computed = self.compute_stat(date_from, date_to, income_categories, expense_categories)
        if not computed["income_categories"] and not computed["expense_categories"]:
            raise ValueError("Отметьте хотя бы одну статью")
        now = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(
            {
                "income_parts": computed["income_parts"],
                "expense_parts": computed["expense_parts"],
            },
            ensure_ascii=False,
        )
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO stat_snapshots (
                    created_at, period_from, period_to,
                    income_categories, expense_categories,
                    income_total, expense_total, net, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    computed["period_from"],
                    computed["period_to"],
                    json.dumps(computed["income_categories"], ensure_ascii=False),
                    json.dumps(computed["expense_categories"], ensure_ascii=False),
                    computed["income"],
                    computed["expense"],
                    computed["net"],
                    payload,
                ),
            )
            snap_id = int(cur.lastrowid)
        return {"id": snap_id, "created_at": now, **computed}

    def list_stat_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stat_snapshots ORDER BY period_from ASC, id ASC"
            ).fetchall()
        return [_public_stat(dict(r)) for r in rows]

    def delete_stat_snapshot(self, snap_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM stat_snapshots WHERE id = ?", (snap_id,))
            return cur.rowcount > 0

    def _focus_key(self, year: int, month: int, part: str) -> str:
        return f"focus_{part}:{int(year):04d}-{int(month):02d}"

    def _prev_month(self, year: int, month: int) -> tuple[int, int]:
        if month <= 1:
            return year - 1, 12
        return year, month - 1

    def _raw_focus_expenses(self, year: int, month: int) -> list[str] | None:
        expense_raw = self.get_setting(self._focus_key(year, month, "expenses"))
        if expense_raw in (None, ""):
            return None
        try:
            parsed = json.loads(expense_raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, list):
            return None
        return [str(item).strip() for item in parsed if str(item).strip()]

    def _month_expense_names(self, year: int, month: int) -> list[str]:
        last = monthrange(int(year), int(month))[1]
        data = self.summary(
            f"{int(year):04d}-{int(month):02d}-01",
            f"{int(year):04d}-{int(month):02d}-{last:02d}",
        )
        return [str(row["name"]) for row in data.get("expense_by_category") or []]

    def resolved_focus_expenses(
        self, year: int, month: int, *, depth: int = 48
    ) -> list[str] | None:
        """Checklist saved this month, or the previous month's selection."""
        explicit = self._raw_focus_expenses(year, month)
        if explicit is not None:
            return explicit
        if depth <= 0 or year < 2000:
            return None
        py, pm = self._prev_month(year, month)
        prev_explicit = self._raw_focus_expenses(py, pm)
        if prev_explicit is not None:
            return prev_explicit
        prev_names = self._month_expense_names(py, pm)
        if prev_names:
            return prev_names
        return self.resolved_focus_expenses(py, pm, depth=depth - 1)

    def focus_article_amounts(
        self, year: int, month: int, names: list[str] | None
    ) -> dict[str, float]:
        """Per-article amounts for focus saldo: spend if any, otherwise plan."""
        last = monthrange(int(year), int(month))[1]
        data = self.summary(
            f"{int(year):04d}-{int(month):02d}-01",
            f"{int(year):04d}-{int(month):02d}-{last:02d}",
        )
        actual = {
            _fold_cat(str(row["name"])): float(row["amount"] or 0)
            for row in data.get("expense_by_category") or []
        }
        plans = {
            _fold_cat(name): float(amount)
            for name, amount in (data.get("plans") or {}).get("expense", {}).items()
        }
        if names is None:
            wanted = {
                str(row["name"]): _fold_cat(str(row["name"]))
                for row in data.get("expense_by_category") or []
            }
            for name in (data.get("plans") or {}).get("expense", {}):
                wanted.setdefault(str(name), _fold_cat(name))
            ordered = list(wanted.items())
        else:
            ordered = [(str(name), _fold_cat(name)) for name in names if str(name).strip()]
        out: dict[str, float] = {}
        for name, key in ordered:
            if not key or key in {_fold_cat(n) for n in out}:
                continue
            spent = actual.get(key, 0.0)
            plan = plans.get(key, 0.0)
            out[name] = round(spent if spent > 0 else (plan if plan > 0 else 0.0), 2)
        return out

    def focus_expense_sum(
        self, year: int, month: int, names: list[str] | None
    ) -> float:
        """Actual spend per article, or that article's plan when spend is still zero."""
        return round(sum(self.focus_article_amounts(year, month, names).values()), 2)

    def focus_stats_series(
        self,
        *,
        months: int = 12,
        end_year: int | None = None,
        end_month: int | None = None,
    ) -> dict[str, Any]:
        """Monthly focus income / expense / saldo for the statistics charts."""
        from .report import month_title

        today = date.today()
        y = int(end_year or today.year)
        m = int(end_month or today.month)
        count = max(1, min(int(months or 12), 36))
        expense_names = self.resolved_focus_expenses(y, m) or []
        points: list[dict[str, Any]] = []
        cy, cm = y, m
        for _ in range(count):
            focus = self.get_focus(cy, cm)
            income = float(focus["income"] or 0)
            articles = self.focus_article_amounts(cy, cm, expense_names)
            expense = round(sum(articles.values()), 2)
            points.append(
                {
                    "year": cy,
                    "month": cm,
                    "ym": f"{cy:04d}-{cm:02d}",
                    "title": month_title(cy, cm),
                    "income": income,
                    "expense": expense,
                    "net": round(income - expense, 2),
                    "has_income": focus["income"] is not None,
                    "articles": articles,
                }
            )
            cy, cm = self._prev_month(cy, cm)
        points.reverse()
        return {
            "months": count,
            "end_year": y,
            "end_month": m,
            "expense_names": expense_names,
            "points": points,
        }

    def get_focus(self, year: int, month: int) -> dict[str, Any]:
        """Manual income and expense articles for the screen saldo. Not the statement."""
        income_raw = self.get_setting(self._focus_key(year, month, "income"))
        income = None
        if income_raw not in (None, ""):
            try:
                income = round(float(income_raw), 2)
            except ValueError:
                income = None
        expenses = self.resolved_focus_expenses(year, month)
        return {
            "income": income,
            "expenses": expenses,
            "expense_sum": self.focus_expense_sum(year, month, expenses),
        }

    def set_focus_income(self, year: int, month: int, amount: float) -> dict[str, Any]:
        if amount < 0:
            raise ValueError("Доход не может быть меньше нуля")
        self.set_setting(
            self._focus_key(year, month, "income"),
            str(round(float(amount), 2)),
        )
        return self.get_focus(year, month)

    def set_focus_expenses(
        self, year: int, month: int, names: list[str]
    ) -> dict[str, Any]:
        clean: list[str] = []
        seen: set[str] = set()
        for name in names:
            text = str(name or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            clean.append(text)
        self.set_setting(
            self._focus_key(year, month, "expenses"),
            json.dumps(clean, ensure_ascii=False),
        )
        return self.get_focus(year, month)

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
    signed_cats: dict[str, float] = {}
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
        signed_cats[cat] = signed_cats.get(cat, 0.0) + amount

    income_cats: dict[str, float] = {}
    expense_cats: dict[str, float] = {}
    for cat, total in signed_cats.items():
        if abs(total) < 0.005:
            continue
        if total > 0:
            income_cats[cat] = total
        else:
            expense_cats[cat] = abs(total)

    # Bars are net per article. Gross income/expense stay as on the statement.
    net_bars = round(sum(income_cats.values()) - sum(expense_cats.values()), 2)
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
        "bars_ok": _money_close(net_bars, income - expense),
    }


def _sorted_cats(d: dict[str, float]) -> list[dict[str, Any]]:
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": k, "amount": round(v, 2)} for k, v in items]


def _clean_cat_list(names: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        key = _fold_cat(name)
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _named_parts(rows: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    by_key = {_fold_cat(str(r.get("name") or "")): r for r in rows}
    parts: list[dict[str, Any]] = []
    for name in names:
        row = by_key.get(_fold_cat(name))
        parts.append(
            {
                "name": str((row or {}).get("name") or name),
                "amount": round(float((row or {}).get("amount") or 0), 2),
            }
        )
    return parts


def _public_stat(row: dict[str, Any]) -> dict[str, Any]:
    def _loads(raw: Any, fallback: Any) -> Any:
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(raw or "")
        except (TypeError, json.JSONDecodeError):
            return fallback

    payload = _loads(row.get("payload"), {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        "id": row["id"],
        "created_at": row.get("created_at") or "",
        "period_from": row["period_from"],
        "period_to": row["period_to"],
        "income_categories": _loads(row.get("income_categories"), []),
        "expense_categories": _loads(row.get("expense_categories"), []),
        "income_total": round(float(row.get("income_total") or 0), 2),
        "expense_total": round(float(row.get("expense_total") or 0), 2),
        "net": round(float(row.get("net") or 0), 2),
        "income_parts": payload.get("income_parts") or [],
        "expense_parts": payload.get("expense_parts") or [],
    }


def public_cash_op(row: dict[str, Any]) -> dict[str, Any]:
    cash_id = int(row["id"])
    amount = float(row["amount"])
    kind = str(row.get("kind") or "")
    note = str(row.get("note") or "").strip()
    if note:
        desc = note
    elif kind == SAVINGS_ADJUST_KIND:
        desc = "Накопления на карте"
    elif kind == ADJUST_KIND:
        desc = "Корректировка наличных"
    elif kind == "from_card" or amount > 0:
        desc = "С карты в наличные"
    else:
        desc = "Оплата наличными"
    posted_date = str(row.get("posted_date") or "")
    return {
        "id": f"c{cash_id}",
        "cash_id": cash_id,
        "cash": True,
        "posted_date": posted_date,
        "posted_at": str(row.get("created_at") or posted_date),
        "amount": round(amount, 2),
        "currency": "RUB",
        "bank_category": "",
        "description": desc,
        "mcc": "",
        "card": "",
        "status": "",
        "note": note,
        "user_category": str(row.get("category") or ""),
        "user_note": note,
        "kind": kind,
        "is_internal": kind == "from_card",
        "needs_review": False,
        "extra": {"cash": True},
    }


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
