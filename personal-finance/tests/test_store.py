"""Ledger import, dedup and transfer review."""

from __future__ import annotations

import json
from pathlib import Path

from app.parse import parse_statement
from app.store import FinanceStore, tx_uid
from tests.test_parse import TINKOFF, _write


def _store(tmp_path: Path) -> FinanceStore:
    return FinanceStore(tmp_path / "ledger.sqlite")


def test_import_dedup_and_review_queue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    txs = parse_statement(_write(TINKOFF))
    first = store.import_transactions(txs, "ops.csv")
    assert first.new_count == 5
    assert first.review_count == 1
    again = store.import_transactions(txs, "ops.csv")
    assert again.new_count == 0
    assert again.dup_count == 5


def test_posted_uid_keeps_legacy_lookup() -> None:
    import hashlib

    txs = parse_statement(_write(TINKOFF))
    food = next(t for t in txs if t.description == "PYATEROCHKA")
    legacy = "|".join(
        [
            food.posted_at.strftime("%Y-%m-%d %H:%M:%S"),
            f"{food.amount:.2f}",
            food.description,
            food.card,
            food.mcc,
            food.category,
        ]
    )
    assert tx_uid(food, legacy=True) == hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    assert tx_uid(food) != tx_uid(food, legacy=True)


def test_unreviewed_not_in_pnl_until_explained(tmp_path: Path) -> None:
    store = _store(tmp_path)
    txs = parse_statement(_write(TINKOFF))
    store.import_transactions(txs, "ops.csv")
    summary = store.summary("2026-08-01", "2026-08-31")
    assert summary["income"] == 150000
    # supermarket 1250.50 + coffee 890 + p2p 50000 + own-account 20000
    assert summary["expense"] == 72140.5
    assert summary["net"] == 150000 - 72140.5
    assert summary["unreviewed_count"] == 1
    assert summary["unreviewed_sum"] == -50000
    assert summary["internal"] == -20000

    pending = store.list_transactions(needs_review=True)
    p2p = pending[0]
    store.review_transaction(
        p2p["id"],
        kind="expense",
        user_category="Подарки",
        user_note="перевод маме",
    )
    after = store.summary("2026-08-01", "2026-08-31")
    assert after["unreviewed_count"] == 0
    assert after["expense"] == 72140.5
    cats = {c["name"]: c["amount"] for c in after["expense_by_category"]}
    assert cats["Подарки"] == 50000
    assert cats["Супермаркеты"] == 1250.5


def test_leave_unlabeled_parks_outside_queue(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.import_transactions(parse_statement(_write(TINKOFF)), "ops.csv")
    pending = store.list_transactions(needs_review=True)
    store.leave_unlabeled(int(pending[0]["id"]))
    summary = store.summary("2026-08-01", "2026-08-31")
    assert summary["unreviewed_count"] == 0
    assert summary["unlabeled_count"] == 1
    assert summary["unlabeled_sum"] == -50000
    assert summary["expense"] == 72140.5
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Переводы без разметки"] == 50000
    assert "Подарки" not in names
    assert summary["bars_ok"] is True


MIXED_SBP = """\
Дата операции;Дата платежа;Номер карты;Статус;Сумма операции;Валюта операции;Сумма платежа;Валюта платежа;Кэшбэк;Категория;MCC;Описание
17.08.2026 10:00:00;17.08.2026;*1111;OK;-1000,00;RUB;-1000,00;RUB;;Переводы;;СБП исходящий
17.08.2026 12:00:00;17.08.2026;*1111;OK;34667,00;RUB;34667,00;RUB;;Переводы;;СБП входящий
17.08.2026 14:00:00;17.08.2026;*1111;OK;2680,00;RUB;2680,00;RUB;;Переводы;;СБП входящий 2
"""


def test_accept_all_income_leaves_outflows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.import_transactions(parse_statement(_write(MIXED_SBP)), "sbp.csv")
    pending = store.list_transactions(needs_review=True)
    assert len(pending) == 3
    accepted = store.accept_all_income()
    assert len(accepted) == 2
    assert all(float(row["amount"]) > 0 for row in accepted)
    assert all(row["kind"] == "income" for row in accepted)
    leftover = store.list_transactions(needs_review=True)
    assert len(leftover) == 1
    assert leftover[0]["amount"] == -1000
    summary = store.summary("2026-08-01", "2026-08-31")
    assert summary["unreviewed_count"] == 1
    assert summary["income"] == 34667 + 2680
    names = {c["name"]: c["amount"] for c in summary["income_by_category"]}
    assert names["Доходы"] == 34667 + 2680


def test_ledger_lists_ops_behind_category_and_totals(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.import_transactions(parse_statement(_write(TINKOFF)), "ops.csv")
    food = store.list_ledger("2026-08-01", "2026-08-31", bucket="expense", category="Супермаркеты")
    assert [row["description"] for row in food] == ["PYATEROCHKA"]
    expenses = store.list_ledger("2026-08-01", "2026-08-31", bucket="expense")
    assert {"PYATEROCHKA", "COFFEE"} <= {row["description"] for row in expenses}
    income = store.list_ledger("2026-08-01", "2026-08-31", bucket="income")
    assert [row["description"] for row in income] == ["Иван Иванов"]
    pending = store.list_transactions(needs_review=True)
    store.leave_unlabeled(int(pending[0]["id"]))
    after = store.list_ledger("2026-08-01", "2026-08-31", bucket="expense")
    assert "Перевод на карту *2222" in {row["description"] for row in after}
    still_food = store.list_ledger(
        "2026-08-01", "2026-08-31", bucket="expense", category="Супермаркеты"
    )
    assert [row["description"] for row in still_food] == ["PYATEROCHKA"]


def test_recategorize_moves_operation_between_articles(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.import_transactions(parse_statement(_write(TINKOFF)), "ops.csv")
    food = store.list_ledger("2026-08-01", "2026-08-31", bucket="expense", category="Супермаркеты")
    updated = store.recategorize(int(food[0]["id"]), user_category="Продукты")
    assert updated["user_category"] == "Продукты"
    summary = store.summary("2026-08-01", "2026-08-31")
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Продукты"] == 1250.5
    assert "Супермаркеты" not in names


POSTED_TSUM = """
Выписка по счету
Операции по счету
Дата проводки Код операции Описание Сумма
в валюте счета
26.08.2026 CRD_9TW2TSUM Операция по карте: 220015++++++7603, на сумму: 28550.00 RUR, дата совершения
операции: 25.08.26, место совершения операции: RU\\MOSCOW\\TSUM ONLINE MCC5651
-28 550,00 RUR
"""


def test_hold_is_saved_as_expense_until_posted(tmp_path: Path) -> None:
    from app.parse_pdf import parse_pdf_text
    from tests.test_pdf import ALFA

    store = _store(tmp_path)
    store.import_transactions(parse_pdf_text(ALFA), "hold.pdf")
    clothes = store.list_ledger(
        "2026-08-01", "2026-08-31", bucket="expense", category="Одежда"
    )
    assert len(clothes) == 1
    row = clothes[0]
    assert row["amount"] == -28550
    assert row["status"] == "hold"
    assert row["description"] == "ЦУМ"
    extra = row["extra"]
    if isinstance(extra, str):
        extra = json.loads(extra)
    assert extra.get("hold") is True
    summary = store.summary("2026-08-01", "2026-08-31")
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Одежда"] == 28550

    posted = store.import_transactions(parse_pdf_text(POSTED_TSUM), "posted.pdf")
    assert posted.new_count == 1
    after = store.list_ledger(
        "2026-08-01", "2026-08-31", bucket="expense", category="Одежда"
    )
    assert len(after) == 1
    assert after[0]["status"] != "hold"
    assert after[0]["description"] == "ЦУМ"


def test_hold_not_imported_if_posted_already_exists(tmp_path: Path) -> None:
    from app.parse_pdf import parse_pdf_text
    from tests.test_pdf import ALFA

    store = _store(tmp_path)
    store.import_transactions(parse_pdf_text(POSTED_TSUM), "posted.pdf")
    again = store.import_transactions(parse_pdf_text(ALFA), "hold.pdf")
    clothes = store.list_ledger(
        "2026-08-01", "2026-08-31", bucket="expense", category="Одежда"
    )
    assert len(clothes) == 1
    assert clothes[0]["status"] != "hold"
    assert again.dup_count >= 1


def test_same_day_piggy_keeps_both_operation_codes(tmp_path: Path) -> None:
    from app.parse_pdf import parse_pdf_text

    text = """
Выписка по счету
За период с 01.08.2026 по 01.08.2026
Поступления 0,00 RUR
Расходы 300,00 RUR
Операции по счету
01.08.2026 OP1EDAAA Перечисление средств в рамках услуги "Копилка для сдачи" со счета 1 на счет 2
-150,00 RUR
01.08.2026 OP1EDBBB Перечисление средств в рамках услуги "Копилка для сдачи" со счета 1 на счет 2
-150,00 RUR
"""
    store = _store(tmp_path)
    txs = parse_pdf_text(text)
    assert len(txs) == 2
    result = store.import_transactions(txs, "piggy.pdf")
    assert result.new_count == 2
    rows = store.list_transactions(date_from="2026-08-01", date_to="2026-08-01")
    assert len(rows) == 2
    assert sum(abs(float(r["amount"])) for r in rows) == 300


def test_hold_not_collapsed_into_unrelated_same_amount(tmp_path: Path) -> None:
    from app.parse_pdf import parse_pdf_text

    text = """
Выписка по счету
Операции по счету
28.08.2026 CRD_MIGUSHA Операция по карте: 220015++++++7603, на сумму: 1150.00 RUR, дата совершения
операции: 28.08.26, место совершения операции: RU\\KRASNOYARSK\\MIGUSHA MCC5812
-1 150,00 RUR
HOLD Неподтвержденная операция: 7AA111 45175380 RU SNEZHNYJ KOFE>Krasnoyarsk 27.08.26 1150.00 RUR 220015++++++7603, дата операции: 27.08.2026
-1 150,00 RUR
"""
    store = _store(tmp_path)
    store.import_transactions(parse_pdf_text(text), "mix.pdf")
    rows = store.list_transactions(date_from="2026-08-01", date_to="2026-08-31")
    assert len(rows) == 2
    holds = [r for r in rows if r["status"] == "hold"]
    assert len(holds) == 1
    assert "KOFE" in (holds[0]["description"] or "").upper() or "SNEZHNYJ" in (
        holds[0]["description"] or ""
    ).upper()


def test_import_reconciles_header_totals(tmp_path: Path) -> None:
    from app.parse_pdf import extract_pdf_meta, parse_pdf_text
    from tests.test_pdf import ALFA

    store = _store(tmp_path)
    txs = parse_pdf_text(ALFA)
    meta = extract_pdf_meta(ALFA)
    result = store.import_transactions(txs, "alfa.pdf", meta=meta)
    rec = result.reconcile
    assert rec is not None
    assert rec["from_header"] is True
    assert rec["matched"] is True
    assert rec["income_ok"] is True
    assert rec["expense_ok"] is True
    summary = store.summary("2026-08-01", "2026-08-31")
    assert summary["reconcile"]["matched"] is True
    assert summary["bars_ok"] is True



