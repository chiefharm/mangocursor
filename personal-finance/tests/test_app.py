"""HTTP API: upload statement, explain a transfer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_parse import TINKOFF, _write


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FINANCE_AUTH", "off")
    monkeypatch.setenv("FINANCE_TELEGRAM_ENABLED", "0")
    monkeypatch.setenv("FINANCE_PASSWORD", "secret")
    from app import main

    main.reset_data_dir(tmp_path)
    return TestClient(main.app)


def test_health(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_upload_and_review_transfer(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        res = client.post("/api/import", files={"file": ("ops.csv", fh, "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["import"]["new_count"] == 5
    assert body["import"]["review_count"] == 1
    assert body["summary"]["unreviewed_count"] == 1

    queue = client.get("/api/review").json()
    assert queue["count"] == 1
    p2p = queue["transactions"][0]
    assert "2222" in p2p["description"]

    saved = client.post(
        f"/api/transactions/{p2p['id']}/review",
        json={
            "kind": "expense",
            "user_category": "Подарки",
            "user_note": "перевод маме",
            "is_internal": False,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["review_count"] == 0
    summary = client.get("/api/summary?year=2026&month=8").json()
    assert summary["summary"]["unreviewed_count"] == 0
    names = {c["name"] for c in summary["summary"]["expense_by_category"]}
    assert "Подарки" in names
    leftover = [c for c in summary["summary"]["expense_by_category"] if "перевод" in c["name"].lower()]
    assert leftover == []

    saved_goal = client.post("/api/goal", json={"amount": "80000", "kind": "net"})
    assert saved_goal.status_code == 200
    assert saved_goal.json()["goal"]["amount"] == 80000
    again = client.get("/api/summary?year=2026&month=8").json()
    assert again["goal"]["amount"] == 80000
    assert "advice" in again


def test_bad_file(client: TestClient) -> None:
    res = client.post(
        "/api/import",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400


def test_upload_iphone_name_without_extension(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        res = client.post(
            "/api/import",
            files={"file": ("Выписка_по_счёту", fh, "application/octet-stream")},
        )
    assert res.status_code == 200, res.text
    assert res.json()["import"]["new_count"] == 5


def test_leave_unlabeled_via_api(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        client.post("/api/import", files={"file": ("ops.csv", fh, "text/csv")})
    p2p = client.get("/api/review").json()["transactions"][0]
    res = client.post("/api/review/unlabeled", json={"id": p2p["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["review_count"] == 0
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    assert summary["unreviewed_count"] == 0
    assert summary["unlabeled_count"] == 1
    assert summary["unlabeled"][0]["user_category"] == "Переводы без разметки"


def test_accept_all_income_via_api(client: TestClient) -> None:
    from tests.test_store import MIXED_SBP

    path = _write(MIXED_SBP)
    with path.open("rb") as fh:
        client.post("/api/import", files={"file": ("sbp.csv", fh, "text/csv")})
    assert client.get("/api/review").json()["count"] == 3
    res = client.post("/api/review/income")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["review_count"] == 1
    assert body["category"] == "Доходы"
    leftover = client.get("/api/review").json()["transactions"]
    assert len(leftover) == 1
    assert leftover[0]["amount"] == -1000
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    assert summary["unreviewed_count"] == 1
    names = {c["name"]: c["amount"] for c in summary["income_by_category"]}
    assert names["Доходы"] == 34667 + 2680


def test_transactions_by_category_via_api(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        client.post("/api/import", files={"file": ("ops.csv", fh, "text/csv")})
    food = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "expense", "category": "Супермаркеты"},
    )
    assert food.status_code == 200, food.text
    body = food.json()
    assert body["count"] == 1
    assert body["transactions"][0]["description"] == "PYATEROCHKA"
    assert body["sum"] == 1250.5
    expenses = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "expense"},
    ).json()
    assert {t["description"] for t in expenses["transactions"]} >= {"PYATEROCHKA", "COFFEE"}
    income = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "income"},
    ).json()
    assert income["count"] == 1
    assert income["transactions"][0]["description"] == "Иван Иванов"


def test_recategorize_via_api(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        client.post("/api/import", files={"file": ("ops.csv", fh, "text/csv")})
    food = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "expense", "category": "Супермаркеты"},
    ).json()["transactions"][0]
    res = client.post(
        f"/api/transactions/{food['id']}/category",
        json={"user_category": "Продукты", "kind": "expense"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["transaction"]["user_category"] == "Продукты"
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Продукты"] == 1250.5
    assert "Супермаркеты" not in names
    empty = client.post(
        f"/api/transactions/{food['id']}/category",
        json={"user_category": "  "},
    )
    assert empty.status_code == 400


def test_rename_and_apply_mcc_via_api(client: TestClient) -> None:
    csv = (
        "Дата операции;Дата платежа;Номер карты;Статус;Сумма операции;Валюта операции;"
        "Сумма платежа;Валюта платежа;Кэшбэк;Категория;MCC;Описание\n"
        "15.08.2026 10:00:00;15.08.2026;*1111;OK;-1250,50;RUB;-1250,50;RUB;;Супермаркеты;5411;PYATEROCHKA\n"
        "16.08.2026 12:00:00;16.08.2026;*1111;OK;-800,00;RUB;-800,00;RUB;;Супермаркеты;5411;MAGNIT\n"
        "18.08.2026 09:00:00;18.08.2026;*1111;OK;-890,00;RUB;-890,00;RUB;;Кафе и рестораны;5812;COFFEE\n"
    )
    res = client.post("/api/import", files={"file": ("ops.csv", csv.encode("utf-8"), "text/csv")})
    assert res.status_code == 200, res.text
    food = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "expense", "category": "Супермаркеты"},
    ).json()["transactions"]
    assert len(food) == 2
    applied = client.post(
        f"/api/transactions/{food[0]['id']}/apply-mcc",
        json={"user_category": "Еда", "kind": "expense"},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["count"] == 2
    assert applied.json()["mcc"] == "5411"
    renamed = client.post(
        "/api/categories/rename",
        json={"old_name": "Еда", "new_name": "Продукты", "kind": "expense"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["count"] == 2
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Продукты"] == 2050.5
    assert "Еда" not in names
    assert "Супермаркеты" not in names
    created = client.post(
        f"/api/transactions/{food[0]['id']}/category",
        json={"user_category": "Кофе с собой", "kind": "expense"},
    )
    assert created.status_code == 200
    chips = client.get("/api/review").json()["categories"]["expense"]
    assert "Кофе с собой" in chips


def test_apply_description_via_api(client: TestClient) -> None:
    csv = (
        "Дата операции;Дата платежа;Номер карты;Статус;Сумма операции;Валюта операции;"
        "Сумма платежа;Валюта платежа;Кэшбэк;Категория;MCC;Описание\n"
        "15.08.2026 10:00:00;15.08.2026;*1111;OK;-1250,50;RUB;-1250,50;RUB;;Супермаркеты;5411;PYATEROCHKA\n"
        "16.08.2026 12:00:00;16.08.2026;*1111;OK;-400,00;RUB;-400,00;RUB;;Супермаркеты;;pyaterochka\n"
        "18.08.2026 09:00:00;18.08.2026;*1111;OK;-890,00;RUB;-890,00;RUB;;Кафе и рестораны;5812;COFFEE\n"
        "19.08.2026 09:00:00;19.08.2026;*1111;OK;200,00;RUB;200,00;RUB;;Пополнения;;PYATEROCHKA\n"
    )
    res = client.post("/api/import", files={"file": ("ops.csv", csv.encode("utf-8"), "text/csv")})
    assert res.status_code == 200, res.text
    food = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 8, "bucket": "expense", "category": "Супермаркеты"},
    ).json()["transactions"]
    pyaterochka = next(row for row in food if row["description"] == "PYATEROCHKA")
    applied = client.post(
        f"/api/transactions/{pyaterochka['id']}/apply-description",
        json={"user_category": "Пятёрочка", "kind": "expense"},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["count"] == 2
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Пятёрочка"] == 1650.5
    assert names["Кафе и рестораны"] == 890
    income = {c["name"] for c in summary["income_by_category"]}
    assert "Пятёрочка" not in income
    extra = (
        "Дата операции;Дата платежа;Номер карты;Статус;Сумма операции;Валюта операции;"
        "Сумма платежа;Валюта платежа;Кэшбэк;Категория;MCC;Описание\n"
        "21.08.2026 10:00:00;21.08.2026;*1111;OK;-100,00;RUB;-100,00;RUB;;Супермаркеты;;PYATEROCHKA\n"
    )
    again = client.post("/api/import", files={"file": ("more.csv", extra.encode("utf-8"), "text/csv")})
    assert again.status_code == 200, again.text
    summary = client.get("/api/summary?year=2026&month=8").json()["summary"]
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Пятёрочка"] == 1750.5


def test_review_later_buttons_are_tappable(client: TestClient) -> None:
    page = client.get("/").text
    assert "static/app.js?v=40" in page
    assert "static/styles.css?v=29" in page
    assert "оплата наличными" in client.get("/static/app.js").text
    js = client.get("/static/app.js").text
    assert 'id="review-later" data-nav="queue"' in js
    assert 'id="tab-queue" data-nav="queue"' in js
    assert 'id="apply-desc"' in js
    assert "data-apply-desc" not in js
    assert "apply-description" in js
    assert "По описанию" not in js
    assert "function saldoColumnDiagram(" in js
    assert "Столбчатая диаграмма" in js
    assert "function bindAppClicks()" in js
    assert "function goBack()" in js
    assert "popstate" in js
    assert "history.pushState" in js
    assert 'state.view = "queue";' in js
    css = client.get("/static/styles.css").text
    tabbar = css.split(".tabbar {", 1)[1].split(".tab {", 1)[0]
    assert "translateX(-50%)" not in tabbar
    assert "left: 0;" in tabbar
    assert "right: 0;" in tabbar
    assert "z-index: 40;" in tabbar


def test_duplicates_endpoint_empty(client: TestClient) -> None:
    res = client.get("/api/duplicates?year=2026&month=9")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["group_count"] == 0
    assert body["extra_count"] == 0
    assert body["period_from"] == "2026-09-01"
    assert body["period_to"] == "2026-09-30"


def test_duplicates_fix_endpoint(client: TestClient) -> None:
    from app.parse_pdf import parse_pdf_text
    from app import main

    pdf = """
Выписка по счету
Операции по счету
10.09.2026 CRD_A Операция по карте: 220015++++++2987, на сумму: 440.00 RUR, дата совершения
операции: 09.09.26, место совершения операции: RU\\Krasnoyarsk\\BLOOM COFFEE MCC5814
-440,00 RUR
"""
    store = main.store
    store.import_transactions(parse_pdf_text(pdf), "sep.pdf")
    bloom = store.list_transactions(date_from="2026-09-01", date_to="2026-09-30")[0]
    store.recategorize(int(bloom["id"]), user_category="Кофе Bloom", kind="expense")
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO transactions (
                uid, import_id, posted_at, posted_date, amount, currency,
                bank_category, description, mcc, card, status, kind,
                user_category, user_note, is_internal, needs_review, extra
            ) VALUES ('twin', ?, ?, ?, ?, 'RUB', 'Кафе и рестораны', ?, ?, ?, '',
                      'expense', '', '', 0, 1, ?)
            """,
            (
                bloom["import_id"],
                bloom["posted_at"],
                bloom["posted_date"],
                bloom["amount"],
                bloom["description"],
                bloom["mcc"],
                bloom["card"],
                bloom["extra"],
            ),
        )
    assert client.get("/api/duplicates?year=2026&month=9").json()["extra_count"] == 1
    fixed = client.post("/api/duplicates/fix?year=2026&month=9")
    assert fixed.status_code == 200
    body = fixed.json()
    assert body["deleted_count"] == 1
    assert client.get("/api/duplicates?year=2026&month=9").json()["group_count"] == 0
    left = store.list_transactions(date_from="2026-09-01", date_to="2026-09-30")
    assert len(left) == 1
    assert left[0]["user_category"] == "Кофе Bloom"


def test_focus_saldo_is_separate_from_statement(client: TestClient) -> None:
    path = _write(TINKOFF)
    with path.open("rb") as fh:
        res = client.post("/api/import", files={"file": ("ops.csv", fh, "text/csv")})
    assert res.status_code == 200, res.text
    summary = client.get("/api/summary?year=2026&month=8").json()
    assert summary["focus"]["income"] is None
    assert summary["focus"]["expenses"] is None
    carried = client.get("/api/summary?year=2026&month=9").json()
    assert "Супермаркеты" in carried["focus"]["expenses"]
    assert "Кафе и рестораны" in carried["focus"]["expenses"]
    assert summary["summary"]["reconcile"]["matched"] is True

    saved = client.post(
        "/api/focus",
        json={"year": 2026, "month": 8, "income": "1 500 000"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["focus"]["income"] == 1500000

    picked = client.post(
        "/api/focus",
        json={"year": 2026, "month": 8, "expenses": ["Супермаркеты"]},
    )
    assert picked.status_code == 200, picked.text
    again = client.get("/api/summary?year=2026&month=8").json()
    assert again["focus"]["income"] == 1500000
    assert again["focus"]["expenses"] == ["Супермаркеты"]
    assert again["summary"]["income"] == 150000
    assert again["summary"]["reconcile"]["matched"] is True

    other = client.get("/api/summary?year=2026&month=9").json()
    assert other["focus"]["income"] is None
    assert other["focus"]["expenses"] == ["Супермаркеты"]

    bad = client.post("/api/focus", json={"year": 2026, "month": 8, "income": -1})
    assert bad.status_code == 400


def test_plans_and_cash_do_not_change_statement_totals(client: TestClient) -> None:
    plan = client.post(
        "/api/plans",
        json={"year": 2026, "month": 9, "kind": "expense", "name": "Кафе", "amount": "100 000"},
    )
    assert plan.status_code == 200, plan.text
    cash = client.post(
        "/api/cash/expense",
        json={"amount": "500", "category": "Кафе", "posted_date": "2026-09-15", "note": "кофе"},
    )
    assert cash.status_code == 200, cash.text
    summary = client.get("/api/summary?year=2026&month=9").json()["summary"]
    assert summary["expense"] == 0
    assert summary["plans"]["expense"]["Кафе"] == 100000
    assert summary["wallets"]["cash"]["amount"] == -500
    names = {c["name"]: c["amount"] for c in summary["expense_by_category"]}
    assert names["Кафе"] == 500
    cafe_ops = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 9, "bucket": "expense", "category": "Кафе"},
    ).json()
    assert cafe_ops["sum"] == 500
    assert cafe_ops["count"] == 1
    assert cafe_ops["transactions"][0]["cash"] is True
    assert cafe_ops["transactions"][0]["description"] == "кофе"
    cash_id = cash.json()["cash_op"]["cash_id"]
    edited = client.post(
        f"/api/cash/{cash_id}",
        json={
            "amount": "700",
            "category": "Такси",
            "posted_date": "2026-09-16",
            "note": "дорога",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["cash_op"]["user_category"] == "Такси"
    again = client.get("/api/summary?year=2026&month=9").json()["summary"]
    moved = {c["name"]: c["amount"] for c in again["expense_by_category"]}
    assert moved["Такси"] == 700
    assert "Кафе" not in moved
    assert again["wallets"]["cash"]["amount"] == -700
    taxi_ops = client.get(
        "/api/transactions",
        params={"year": 2026, "month": 9, "bucket": "expense", "category": "Такси"},
    ).json()
    assert taxi_ops["sum"] == 700
    assert taxi_ops["transactions"][0]["cash"] is True
    body = client.get("/api/summary?year=2026&month=9").json()
    assert "Такси" in body["categories"]["expense"]
    assert body["focus"]["expense_sum"] == 100700


def test_expense_plan_and_selection_carry_forward(client: TestClient) -> None:
    saved = client.post(
        "/api/plans",
        json={"year": 2026, "month": 9, "kind": "expense", "name": "Кафе", "amount": "100000"},
    )
    assert saved.status_code == 200, saved.text
    focus = client.post(
        "/api/focus",
        json={
            "year": 2026,
            "month": 9,
            "income": "2000000",
            "expenses": ["Кафе", "Такси"],
        },
    )
    assert focus.status_code == 200, focus.text

    october = client.get("/api/summary?year=2026&month=10").json()
    assert october["summary"]["expense"] == 0
    assert october["summary"]["tx_count"] == 0
    assert october["summary"]["plans"]["expense"]["Кафе"] == 100000
    assert october["focus"]["income"] is None
    assert october["focus"]["expenses"] == ["Кафе", "Такси"]
    assert october["focus"]["expense_sum"] == 100000

    november = client.get("/api/summary?year=2026&month=11").json()
    assert november["summary"]["plans"]["expense"]["Кафе"] == 100000
    assert november["focus"]["expenses"] == ["Кафе", "Такси"]

    changed = client.post(
        "/api/plans",
        json={"year": 2026, "month": 10, "kind": "expense", "name": "Кафе", "amount": "80000"},
    )
    assert changed.status_code == 200, changed.text
    october = client.get("/api/summary?year=2026&month=10").json()
    november = client.get("/api/summary?year=2026&month=11").json()
    september = client.get("/api/summary?year=2026&month=9").json()
    assert october["summary"]["plans"]["expense"]["Кафе"] == 80000
    assert october["focus"]["expense_sum"] == 80000
    assert november["summary"]["plans"]["expense"]["Кафе"] == 80000
    assert september["summary"]["plans"]["expense"]["Кафе"] == 100000

    picked = client.post(
        "/api/focus",
        json={"year": 2026, "month": 10, "expenses": ["Кафе"]},
    )
    assert picked.status_code == 200, picked.text
    assert client.get("/api/summary?year=2026&month=11").json()["focus"]["expenses"] == ["Кафе"]
    assert client.get("/api/summary?year=2026&month=9").json()["focus"]["expenses"] == ["Кафе", "Такси"]

    cleared = client.post(
        "/api/plans",
        json={"year": 2026, "month": 10, "kind": "expense", "name": "Кафе", "amount": 0},
    )
    assert cleared.status_code == 200, cleared.text
    assert "Кафе" not in client.get("/api/summary?year=2026&month=11").json()["summary"]["plans"]["expense"]
    assert client.get("/api/summary?year=2026&month=9").json()["summary"]["plans"]["expense"]["Кафе"] == 100000


def test_stats_series_uses_focus_saldo(client: TestClient) -> None:
    client.post(
        "/api/plans",
        json={"year": 2026, "month": 9, "kind": "expense", "name": "Кафе", "amount": "100000"},
    )
    client.post(
        "/api/focus",
        json={"year": 2026, "month": 9, "income": "2000000", "expenses": ["Кафе"]},
    )
    series = client.get("/api/stats/series?months=3&year=2026&month=10")
    assert series.status_code == 200, series.text
    body = series.json()
    assert body["months"] == 3
    assert body["expense_names"] == ["Кафе"]
    by_ym = {p["ym"]: p for p in body["points"]}
    assert by_ym["2026-09"]["income"] == 2000000
    assert by_ym["2026-09"]["expense"] == 100000
    assert by_ym["2026-09"]["net"] == 1900000
    assert by_ym["2026-09"]["articles"]["Кафе"] == 100000
    assert by_ym["2026-10"]["income"] == 0
    assert by_ym["2026-10"]["expense"] == 100000
    assert by_ym["2026-10"]["has_income"] is False


def test_cash_income_and_expense_dates_can_change(client: TestClient) -> None:
    expense = client.post(
        "/api/cash/expense",
        json={"amount": "200", "category": "Кафе", "posted_date": "2026-09-15", "note": "кофе"},
    )
    assert expense.status_code == 200, expense.text
    income = client.post(
        "/api/cash/from-card",
        json={"amount": "1000", "posted_date": "2026-09-10", "note": "снял"},
    )
    assert income.status_code == 200, income.text

    moved_expense = client.post(
        f"/api/cash/{expense.json()['cash_op']['cash_id']}",
        json={"amount": "200", "category": "Кафе", "posted_date": "2026-09-20", "note": "кофе"},
    )
    assert moved_expense.status_code == 200, moved_expense.text
    assert moved_expense.json()["cash_op"]["posted_date"] == "2026-09-20"

    moved_income = client.post(
        f"/api/cash/{income.json()['cash_op']['cash_id']}",
        json={"amount": "1000", "posted_date": "2026-10-03", "note": "снял"},
    )
    assert moved_income.status_code == 200, moved_income.text
    saved = moved_income.json()["cash_op"]
    assert saved["posted_date"] == "2026-10-03"
    assert saved["amount"] == 1000

    september = client.get("/api/summary?year=2026&month=9").json()["summary"]["cash_ops"]
    october = client.get("/api/summary?year=2026&month=10").json()["summary"]["cash_ops"]
    assert any(op["posted_date"] == "2026-09-20" for op in september)
    assert all(op["posted_date"] != "2026-10-03" for op in september)
    assert any(op["posted_date"] == "2026-10-03" and op["amount"] == 1000 for op in october)



