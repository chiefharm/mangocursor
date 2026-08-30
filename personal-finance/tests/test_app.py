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
    assert "static/app.js?v=19" in page
    assert "static/styles.css?v=19" in page
    js = client.get("/static/app.js").text
    assert 'id="review-later" data-nav="queue"' in js
    assert 'id="tab-queue" data-nav="queue"' in js
    assert 'id="apply-desc"' in js
    assert "data-apply-desc" in js
    assert "apply-description" in js
    assert "function bindAppClicks()" in js
    assert "state.view = \"queue\";\n  state.reviewId = null;\n  render();" in js
    css = client.get("/static/styles.css").text
    tabbar = css.split(".tabbar {", 1)[1].split(".tab {", 1)[0]
    assert "translateX(-50%)" not in tabbar
    assert "left: 0;" in tabbar
    assert "right: 0;" in tabbar
    assert "z-index: 40;" in tabbar



