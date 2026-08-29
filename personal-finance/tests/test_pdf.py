"""Alfa-Bank PDF statement parser — dates come from operations, not the filename."""

from __future__ import annotations

from app.parse_pdf import parse_pdf_text

ALFA = """
Выписка по счету
За период с 01.08.2026 по 28.08.2026
Поступления 10 000,00 RUR
Расходы 1 500,00 RUR
Операции по счету
Дата проводки Код операции Описание Сумма
в валюте счета
01.08.2026 OP1ED2681001LSV4 Перечисление средств в рамках услуги "Копилка для сдачи" со счета
40817810000000000000 на счет 40817810000000000001
-150,00 RUR
01.08.2026 C160108260561099 Перевод C160108260561099 через Систему быстрых платежей на +7 (900) 000-00-00. Без НДС.
-4 000,00 RUR
01.08.2026 CRD_9TW2RN Операция по карте: 220015++++++2987, на сумму: 2059.00 RUR, дата совершения
операции: 29.07.26, место совершения операции: 30653271\\RU\\SANKT
PETERBU\\SBER 5411 SAMO MCC5411
-2 059,00 RUR
А.А. Панченко
Уполномоченное лицо
(подпись сотрудника АО «АЛЬФА-БАНК») (Ф.И.О. сотрудника АО «АЛЬФА-БАНК»)
Страница 2 из 2
Дата проводки Код операции Описание Сумма
в валюте счета
04.08.2026 B010408260784565 Внутрибанковский перевод между счетами, Иванов И. И.
15 000,00 RUR
07.08.2026 OP1ED2687001W7YH Для зачисления на персональную карту ИП.Налог на доходы удержан. НДС не облагается
10 000,00 RUR
HOLD Неподтвержденная операция: 1EE4HB TSUM ONLINE 25.08.26 28550.00 RUR, дата операции: 25.08.2026
-28 550,00 RUR
"""


def test_alfa_pdf_uses_posting_dates_and_keeps_holds() -> None:
    txs = parse_pdf_text(ALFA, filename="random-name.pdf")
    assert [t.posted_date.isoformat() for t in txs] == [
        "2026-08-01",
        "2026-08-01",
        "2026-08-01",
        "2026-08-04",
        "2026-08-07",
        "2026-08-25",
    ]

    piggy = next(t for t in txs if t.amount == -150)
    assert piggy.suggested_internal is True
    assert piggy.needs_review is False

    sbp = next(t for t in txs if t.amount == -4000)
    assert sbp.needs_review is True

    card = next(t for t in txs if t.amount == -2059)
    assert card.category == "Супермаркеты"
    assert card.card == "*2987"
    assert card.needs_review is False

    intra = next(t for t in txs if t.amount == 15000)
    assert intra.suggested_internal is True
    assert intra.needs_review is False

    ip = next(t for t in txs if t.amount == 10000)
    assert ip.suggested_kind == "income"
    assert ip.category == "ИП"
    assert ip.needs_review is False

    tsum = next(t for t in txs if abs(t.amount) == 28550)
    assert tsum.amount == -28550
    assert tsum.posted_date.isoformat() == "2026-08-25"
    assert tsum.category == "Одежда"
    assert tsum.description == "ЦУМ"
    assert tsum.status == "hold"
    assert tsum.extra.get("hold") is True
    assert tsum.needs_review is False
    assert tsum.suggested_kind == "expense"
