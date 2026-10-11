#!/usr/bin/env python3
"""One-shot: merge «Аптеки»→«Здоровье» and «Книги»→«Покупки»."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.store import FinanceStore

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ledger.sqlite"


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"no db: {DB}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = DB.with_name(f"ledger.sqlite.bak-merge-pharm-books-{stamp}")
    shutil.copy2(DB, backup)
    store = FinanceStore(DB)
    a = store.rename_category("Аптеки", "Здоровье", "expense")
    b = store.rename_category("Книги", "Покупки", "expense")
    # legacy label from PDF name helper
    c = store.rename_category("Литрес", "Покупки", "expense")
    summary = store.summary("2026-09-01", "2026-09-30")
    names = {row["name"]: row["amount"] for row in summary["expense_by_category"]}
    print(f"backup: {backup}")
    print(f"аптеки: {a}")
    print(f"книги: {b}")
    print(f"литрес: {c}")
    print(f"sept Здоровье: {names.get('Здоровье')}")
    print(f"sept Покупки: {names.get('Покупки')}")
    print(f"sept Аптеки: {names.get('Аптеки')}")
    print(f"sept Книги: {names.get('Книги')}")
    print(f"focus: {store._raw_focus_expenses(2026, 9)}")


if __name__ == "__main__":
    main()
