"""List likely duplicate ledger rows for a month (audit before stats)."""

from __future__ import annotations

import argparse
import calendar
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .store import FinanceStore


def _period(year: int | None, month: int | None) -> tuple[str, str]:
    today = date.today()
    y = year or today.year
    m = month or today.month
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1).isoformat(), date(y, m, last).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Показать вероятные дубли операций за месяц"
    )
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument(
        "--db",
        default="",
        help="Путь к ledger.sqlite (по умолчанию FINANCE_DATA_DIR/ledger.sqlite)",
    )
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent.parent
    load_dotenv(base / ".env")
    data_dir = Path(os.getenv("FINANCE_DATA_DIR", str(base / "data")))
    db_path = Path(args.db) if args.db else data_dir / "ledger.sqlite"
    date_from, date_to = _period(args.year, args.month)
    store = FinanceStore(db_path)
    groups = store.find_duplicate_groups(date_from, date_to)
    extra = sum(int(g.get("extra_count") or 0) for g in groups)
    print(f"Период {date_from} … {date_to}")
    print(f"Групп-двойников: {len(groups)}, лишних строк: {extra}")
    if not groups:
        print("Дублей не видно — статистика за месяц без задвоенных строк.")
        return 0
    for g in groups:
        code = g.get("code") or "—"
        print(
            f"\n{g['posted_date']}  {g['amount']:+.2f}  код {code}  "
            f"×{g['count']}  (оставить id={g['keeper_id']} «{g['keeper_category']}»)"
        )
        print(f"  {(g.get('description') or '')[:90]}")
        for row in g.get("rows") or []:
            mark = "KEEP" if int(row["id"]) == int(g["keeper_id"]) else "drop"
            cat = (row.get("user_category") or row.get("bank_category") or "—").strip()
            review = "очередь" if int(row.get("needs_review") or 0) else "ok"
            print(f"  [{mark}] id={row['id']}  {cat}  {review}")
    print(
        "\nЧтобы схлопнуть: залей ту же/более широкую выписку после деплоя PR #8 "
        "(или python -m app.pull)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
