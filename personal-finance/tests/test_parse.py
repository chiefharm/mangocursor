"""Bank statement parser tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from openpyxl import Workbook

from app.parse import ParseError, parse_amount, parse_statement, rows_to_transactions, sniff_kind

TINKOFF = dedent(
    """\
    Дата операции;Дата платежа;Номер карты;Статус;Сумма операции;Валюта операции;Сумма платежа;Валюта платежа;Кэшбэк;Категория;MCC;Описание
    15.08.2026 10:00:00;15.08.2026;*1111;OK;-1250,50;RUB;-1250,50;RUB;;Супермаркеты;5411;PYATEROCHKA
    16.08.2026 12:00:00;16.08.2026;*1111;OK;150000,00;RUB;150000,00;RUB;;Пополнения;;Иван Иванов
    17.08.2026 18:00:00;17.08.2026;*1111;OK;-50000,00;RUB;-50000,00;RUB;;Переводы;;Перевод на карту *2222
    18.08.2026 09:00:00;18.08.2026;*1111;OK;-890,00;RUB;-890,00;RUB;;Кафе и рестораны;5812;COFFEE
    19.08.2026 11:00:00;19.08.2026;*1111;FAILED;-100,00;RUB;-100,00;RUB;;Супермаркеты;5411;FAILED TX
    20.08.2026 15:00:00;20.08.2026;*1111;OK;-20000,00;RUB;-20000,00;RUB;;Переводы между своими счетами;;На накопительный
    """
)


def _write(text: str, *, encoding: str = "utf-8") -> Path:
    folder = Path(tempfile.mkdtemp())
    path = folder / "ops.csv"
    path.write_bytes(text.encode(encoding))
    return path


def test_tinkoff_uses_bank_categories_and_flags_transfers() -> None:
    txs = parse_statement(_write(TINKOFF))
    assert len(txs) == 5  # FAILED skipped
    by_desc = {t.description: t for t in txs}

    food = by_desc["PYATEROCHKA"]
    assert food.amount == -1250.50
    assert food.category == "Супермаркеты"
    assert food.needs_review is False
    assert food.suggested_kind == "expense"

    income = by_desc["Иван Иванов"]
    assert income.amount == 150000
    assert income.suggested_kind == "income"
    assert income.needs_review is False

    p2p = by_desc["Перевод на карту *2222"]
    assert p2p.needs_review is True
    assert p2p.suggested_kind == "transfer"
    assert p2p.suggested_internal is False

    own = by_desc["На накопительный"]
    assert own.needs_review is False
    assert own.suggested_internal is True


def test_cp1251_tinkoff() -> None:
    txs = parse_statement(_write(TINKOFF, encoding="cp1251"))
    assert any(t.category == "Супермаркеты" for t in txs)


def test_header_not_on_first_row() -> None:
    text = "Счёт;*1111\n\n" + TINKOFF
    txs = parse_statement(_write(text))
    assert len(txs) == 5


def test_empty_category_needs_review() -> None:
    rows = [
        ["Дата", "Сумма", "Категория", "Описание"],
        ["01.08.2026", "-3000", "", "СБП перевод Мария"],
    ]
    txs = rows_to_transactions(rows)
    assert txs[0].needs_review is True


def test_debit_credit_columns() -> None:
    rows = [
        ["Дата", "Дебет", "Кредит", "Категория", "Описание"],
        ["02.08.2026", "1200,00", "", "Транспорт", "Метро"],
        ["03.08.2026", "", "50000", "Зарплата", "ООО Ромашка"],
    ]
    txs = rows_to_transactions(rows)
    assert txs[0].amount == -1200
    assert txs[1].amount == 50000
    assert txs[1].suggested_kind == "income"


def test_xlsx_tinkoff_like() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата операции", "Сумма", "Категория", "Описание"])
    ws.append(["05.08.2026 12:00:00", -430.0, "Аптеки", "RIGLA"])
    folder = Path(tempfile.mkdtemp())
    path = folder / "ops.xlsx"
    wb.save(path)
    txs = parse_statement(path)
    assert txs[0].category == "Аптеки"
    assert txs[0].amount == -430


def test_not_a_statement() -> None:
    try:
        parse_statement(_write("foo,bar\n1,2\n"))
        raise AssertionError("should fail")
    except ParseError:
        pass


def test_parse_amount_formats() -> None:
    assert parse_amount("-1 250,50") == -1250.50
    assert parse_amount("(200)") == -200
    assert parse_amount("1.500,00") == 1500
    assert parse_amount(12) == 12


def test_sniff_pdf_without_extension(tmp_path: Path) -> None:
    pdf = tmp_path / "Выписка_по_счёту"
    pdf.write_bytes(b"%PDF-1.3\n%\xe2\xe3\xcf\xd3\n")
    assert sniff_kind(pdf, "Выписка_по_счёту") == "pdf"
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8)
    try:
        sniff_kind(photo, "photo.jpg")
        raise AssertionError("photo must fail")
    except ParseError:
        pass
