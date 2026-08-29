from app.advice import build_digest, find_spikes, parse_goal_amount
from app.report import telegram_digest_message, telegram_pending_message
from app.store import FinanceStore
from app.bot import handle_callback, handle_command


def test_parse_goal_amount() -> None:
    assert parse_goal_amount("80000") == 80000
    assert parse_goal_amount("80 000") == 80000
    assert parse_goal_amount("80к") == 80000
    assert parse_goal_amount("/цель 80 тыс") == 80000
    assert parse_goal_amount("нет") is None


def test_spikes_need_baseline_and_threshold() -> None:
    current = [
        {"name": "Кафе", "amount": 22000},
        {"name": "Продукты", "amount": 31000},
        {"name": "Связь", "amount": 800},
    ]
    previous = [
        {"name": "Кафе", "amount": 8000},
        {"name": "Продукты", "amount": 30000},
        {"name": "Связь", "amount": 700},
    ]
    spikes = find_spikes(current, previous)
    names = [s.name for s in spikes]
    assert names == ["Кафе"]
    assert spikes[0].diff == 14000


def test_recs_respect_normal_stance_and_goal_gap() -> None:
    summary = {
        "period": {"from": "2026-08-01", "to": "2026-08-31"},
        "income": 150000,
        "expense": 120000,
        "net": 30000,
        "unreviewed_count": 0,
        "expense_by_category": [
            {"name": "Кафе", "amount": 22000},
            {"name": "Такси", "amount": 16000},
        ],
    }
    previous = {
        "tx_count": 10,
        "expense_by_category": [
            {"name": "Кафе", "amount": 8000},
            {"name": "Такси", "amount": 4000},
        ],
    }
    digest = build_digest(
        summary,
        previous,
        goal={"kind": "net", "amount": 80000},
        stances={"кафе": "normal"},
    )
    assert digest.gap == 50000
    cats = [r.category for r in digest.recs]
    assert "Кафе" not in cats
    assert "Такси" in cats
    text = telegram_digest_message(digest)
    assert "До цели не хватает" in text
    assert "Такси" in text


def test_pending_message_does_not_give_advice() -> None:
    text = telegram_pending_message(
        imported={"new_count": 12, "dup_count": 0},
        summary={"unreviewed_count": 7, "unreviewed_sum": -50000},
    )
    assert "Итоги" in text
    assert "советы" in text
    assert "Как дотянуть" not in text


def test_goal_and_callback_persist(tmp_path) -> None:
    store = FinanceStore(tmp_path / "ledger.sqlite")
    assert "80 000" in handle_command(store, "/цель 80к")
    assert store.get_goal()["amount"] == 80000
    digest_id = store.save_digest(
        {
            "period_from": "2026-08-01",
            "period_to": "2026-08-31",
            "income": 1,
            "expense": 1,
            "net": 0,
            "spikes": [{"name": "Кафе", "current": 22, "previous": 8, "diff": 14}],
            "recs": [],
        }
    )
    toast = handle_callback(store, f"fb:{digest_id}:0:n")
    assert "норма" in toast
    assert store.stances()["кафе"] == "normal"
    assert "оставляем" in handle_callback(store, "goal:ok")
    assert "/цель" in handle_callback(store, "goal:edit")
