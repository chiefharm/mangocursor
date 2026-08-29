from app.report import format_period, money, telegram_import_message


def test_money_and_period() -> None:
    assert money(185000) == "185 000 ₽"
    assert money(-97430.5) == "−97 430,50 ₽"
    assert format_period("2026-08-01", "2026-08-28") == "1–28 августа"


def test_telegram_mentions_unlabeled_transfers() -> None:
    text = telegram_import_message(
        filename="ops.csv",
        imported={"new_count": 5, "dup_count": 1},
        summary={
            "period": {"from": "2026-08-01", "to": "2026-08-28"},
            "income": 150000,
            "expense": 2140.5,
            "net": 147859.5,
            "expense_by_category": [{"name": "Супермаркеты", "amount": 1250.5}],
            "income_by_category": [{"name": "Пополнения", "amount": 150000}],
            "unreviewed_count": 2,
            "unreviewed_sum": -70000,
        },
        previous={"income": 100000, "expense": 5000},
    )
    assert "Личные финансы" in text
    assert "Нужно пояснить" in text
    assert "2" in text
    assert "Супермаркеты" in text
    assert "К прошлому периоду" in text
