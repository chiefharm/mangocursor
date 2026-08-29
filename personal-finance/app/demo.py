"""Sample month so the preview is not an empty shell."""

from __future__ import annotations

from datetime import datetime

from .parse import ParsedTx
from .store import FinanceStore


def seed_if_empty(store: FinanceStore) -> None:
    if store.list_imports():
        return
    july = [
        _tx("2026-07-05 11:20:00", -28400, "Супермаркеты", "PYATEROCHKA"),
        _tx("2026-07-08 19:10:00", -7200, "Кафе и рестораны", "COFFEE"),
        _tx("2026-07-12 09:00:00", -4100, "Такси", "YANDEX GO"),
        _tx("2026-07-15 10:00:00", 148000, "Пополнения", "Зарплата"),
        _tx("2026-07-22 21:00:00", -1900, "Связь", "MEGAFON"),
    ]
    august = [
        _tx("2026-08-03 12:40:00", -30100, "Супермаркеты", "PYATEROCHKA"),
        _tx("2026-08-06 18:20:00", -21400, "Кафе и рестораны", "COFFEE"),
        _tx("2026-08-09 08:50:00", -15800, "Такси", "YANDEX GO"),
        _tx("2026-08-12 10:00:00", 150000, "Пополнения", "Зарплата"),
        _tx("2026-08-17 18:00:00", -50000, "Переводы", "Перевод на карту *2222"),
        _tx("2026-08-20 14:00:00", -890, "Кафе и рестораны", "PEKAR"),
        _tx("2026-08-20 15:00:00", -20000, "Переводы между своими счетами", "На накопительный"),
    ]
    store.import_transactions(july, "demo-july.csv")
    store.import_transactions(august, "demo-august.csv")
    store.set_goal(80000, "net")


def _tx(when: str, amount: float, category: str, description: str) -> ParsedTx:
    posted = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    from .parse import classify_review

    needs, kind, internal = classify_review(category, description, amount)
    return ParsedTx(
        posted_at=posted,
        amount=amount,
        category=category,
        description=description,
        needs_review=needs,
        suggested_kind=kind,
        suggested_internal=internal,
    )
