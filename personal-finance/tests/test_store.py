"""Ledger import, dedup and transfer review."""

from __future__ import annotations

from pathlib import Path

from app.parse import parse_statement
from app.store import FinanceStore
from tests.test_parse import TINKOFF, _write


def _store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(tmp_path / "ledger.sqlite")


def test_import_dedup_and_review_queue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    txs = parse_statement(_write(TINKOFF))
    first = store.import_transactions(txs, "ops.csv")
    assert first.new_count == 5
    assert first.review_count == 2
    again = store.import_transactions(txs, "ops.csv")
    assert again.new_count == 0
    assert again.dup_count == 5


def test_unreviewed_not_in_pnl_until_explained(tmp_path: Path) -> None:
    store = _store(tmp_path)
    txs = parse_statement(_write(TINKOFF))
    store.import_transactions(txs, "ops.csv")
    summary = store.summary("2026-08-01", "2026-08-31")
    assert summary["income"] == 150000
    # supermarket 1250.50 + coffee 890; transfers held aside
    assert summary["expense"] == 2140.5
    assert summary["unreviewed_count"] == 2
    assert summary["unreviewed_sum"] == -70000

    pending = store.list_transactions(needs_review=True)
    own = next(t for t in pending if "накопительн" in t["description"].lower())
    store.review_transaction(
        own["id"], kind="transfer", user_note="на копилку", is_internal=True
    )
    p2p = next(t for t in pending if t["id"] != own["id"])
    store.review_transaction(
        p2p["id"],
        kind="expense",
        user_category="Подарки",
        user_note="перевод маме",
    )
    after = store.summary("2026-08-01", "2026-08-31")
    assert after["unreviewed_count"] == 0
    assert after["expense"] == 2140.5 + 50000
    cats = {c["name"]: c["amount"] for c in after["expense_by_category"]}
    assert cats["Подарки"] == 50000
    assert cats["Супермаркеты"] == 1250.5
