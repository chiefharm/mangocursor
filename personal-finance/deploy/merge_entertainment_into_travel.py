#!/usr/bin/env python3
"""One-shot: merge «Развлечения» into «Путешествия» on the live ledger."""

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
    backup = DB.with_name(f"ledger.sqlite.bak-merge-travel-{stamp}")
    shutil.copy2(DB, backup)
    store = FinanceStore(DB)
    result = store.rename_category("Развлечения", "Путешествия", "expense")
    summary = store.summary("2026-09-01", "2026-09-30")
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    print(f"backup: {backup}")
    print(f"renamed: {result}")
    print(f"sept Путешествия: {names.get('Путешествия')}")
    print(f"sept Развлечения: {names.get('Развлечения')}")
    print(f"focus: {store._raw_focus_expenses(2026, 9)}")


if __name__ == "__main__":
    main()
