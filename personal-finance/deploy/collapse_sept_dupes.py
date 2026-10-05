#!/usr/bin/env python3
"""One-shot: collapse September twin rows in /opt/personal-finance/data/ledger.sqlite.

Safe to run on the VPS without deploying new app code.
Keeps the user-sorted row in each group; deletes the extras.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/personal-finance/data/ledger.sqlite")
DATE_FROM = "2026-09-01"
DATE_TO = "2026-09-30"
FIX = "--fix" in sys.argv or "-f" in sys.argv


def extra_code(raw: str | None) -> str:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("code") or "").strip()


def desc_key(raw: str | None) -> str:
    return " ".join(str(raw or "").split()).casefold()


def keeper_rank(row: sqlite3.Row) -> tuple:
    has_user = 1 if (row["user_category"] or "").strip() else 0
    has_note = 1 if (row["user_note"] or "").strip() else 0
    out_of_queue = 0 if int(row["needs_review"] or 0) else 1
    return (has_user, out_of_queue, has_note, -int(row["id"]))


def main() -> int:
    if not DB.exists():
        print(f"Нет базы: {DB}")
        return 1
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM transactions
        WHERE posted_date >= ? AND posted_date <= ?
          AND LOWER(COALESCE(status, '')) != 'hold'
        ORDER BY id
        """,
        (DATE_FROM, DATE_TO),
    ).fetchall()
    buckets: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        code = extra_code(row["extra"])
        amount_key = round(float(row["amount"] or 0), 2)
        if code:
            key = (row["posted_date"], amount_key, "code", code)
        else:
            key = (
                row["posted_date"],
                amount_key,
                "bare",
                (row["mcc"] or "").strip(),
                (row["card"] or "").strip(),
                desc_key(row["description"]),
            )
        buckets[key].append(row)

    groups = [items for items in buckets.values() if len(items) >= 2]
    extra = sum(len(g) - 1 for g in groups)
    print(f"Период {DATE_FROM} … {DATE_TO}")
    print(f"Групп-двойников: {len(groups)}, лишних строк: {extra}")
    if not groups:
        print("Дублей нет.")
        return 0

    deleted = 0
    for items in sorted(groups, key=lambda g: (g[0]["posted_date"], abs(float(g[0]["amount"])))):
        keeper = max(items, key=keeper_rank)
        cat = (keeper["user_category"] or keeper["bank_category"] or "—").strip()
        print(
            f"\n{keeper['posted_date']}  {float(keeper['amount']):+.2f}  "
            f"×{len(items)}  оставить id={keeper['id']} «{cat}»"
        )
        print(f"  {(keeper['description'] or '')[:90]}")
        for row in items:
            mark = "KEEP" if int(row["id"]) == int(keeper["id"]) else "drop"
            print(f"  [{mark}] id={row['id']}")
            if FIX and int(row["id"]) != int(keeper["id"]):
                conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
                deleted += 1

    if not FIX:
        print("\nЭто только просмотр. Чтобы удалить лишнее, запусти с --fix")
        return 0
    conn.commit()
    print(f"\nГотово: удалено {deleted} лишних строк. Разнесённые оставлены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
