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
    assert body["import"]["review_count"] == 2
    assert body["summary"]["unreviewed_count"] == 2

    queue = client.get("/api/review").json()
    assert queue["count"] == 2
    p2p = next(t for t in queue["transactions"] if "2222" in t["description"])
    own = next(t for t in queue["transactions"] if t["id"] != p2p["id"])

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
    assert saved.json()["review_count"] == 1

    client.post(
        f"/api/transactions/{own['id']}/review",
        json={
            "kind": "transfer",
            "user_note": "на накопительный",
            "is_internal": True,
        },
    )
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
