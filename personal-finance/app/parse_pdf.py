"""PDF bank statements — Alfa-Bank account export and similar layouts."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .mcc import category_for_mcc
from .parse import ParseError, ParsedTx, classify_review, parse_amount, parse_datetime

_FOOTER = [
    r"А\.А\. Панченко",
    r"Уполномоченное лицо",
    r"\(подпись сотрудника АО «АЛЬФА-БАНК»\) \(Ф\.И\.О\. сотрудника АО «АЛЬФА-БАНК»\)",
    r"Страница \d+ из \d+",
    r"Дата проводки Код операции Описание Сумма",
    r"в валюте счета",
]
_START = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s+(\S+)\s*(.*)$")
_HOLD = re.compile(r"^HOLD\b")
_AMT_ONLY = re.compile(r"^([+\-−]?\s*\d[\d \u00a0]*,\d{2})\s+RU[RB]$", re.I)
_AMT_ANY = re.compile(r"([+\-−]?\s*\d[\d \u00a0]*,\d{2})\s+RU[RB]\b", re.I)
_MCC = re.compile(r"MCC(\d{4})")
_CARD = re.compile(r"(?:карте|карты)[:\s]+(\d+\++\d+)", re.I)
_OP_DATE = re.compile(
    r"дата совершения\s*операции:\s*(\d{2}\.\d{2}\.\d{2,4})",
    re.I,
)
_OWN = (
    "копилка",
    "внутрибанковский перевод между счетами",
    "между своими",
)
_IP_INCOME = "для зачисления на персональную карту ип"
_CASH_IN = ("внесение средств", "cashin", "recycling")
_CREDIT_PAY = ("погаш. задолж", "погашение задолженности", "кредитн")


def parse_pdf_statement(path: str | Path, *, filename: str | None = None) -> list[ParsedTx]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 — surface as a parse error, not a 500
        raise ParseError("Не удалось прочитать PDF. Нужна выписка Альфа как файл, не фото экрана.") from exc
    if reader.is_encrypted:
        raise ParseError("PDF закрыт паролем")
    try:
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise ParseError("В PDF не получилось достать текст операций.") from exc
    if not text.strip():
        raise ParseError("В PDF нет текста — нужна выписка, а не скан без слоя")
    return parse_pdf_text(text, filename=filename or Path(path).name)


def parse_pdf_text(text: str, *, filename: str = "statement.pdf") -> list[ParsedTx]:
    cleaned = _strip_noise(text)
    ops = _split_ops(cleaned)
    out: list[ParsedTx] = []
    for op in ops:
        if op["hold"]:
            continue
        tx = _op_to_tx(op)
        if tx is None:
            continue
        out.append(tx)
    if not out:
        raise ParseError(f"В {filename} нет ни одной операции")
    return out


def _strip_noise(text: str) -> str:
    cleaned = text.replace("\xa0", " ")
    for pat in _FOOTER:
        cleaned = re.sub(pat, "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _split_ops(text: str) -> list[dict[str, str | bool]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    ops: list[dict[str, str | bool]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _HOLD.match(line):
            blob, amount, i = _collect_until_amount(lines, i + 1, [line])
            ops.append({"hold": True, "date": "", "code": "HOLD", "desc": blob, "amount": amount})
            continue
        m = _START.match(line)
        if not m:
            i += 1
            continue
        posted, code, rest = m.groups()
        amount = ""
        desc_parts: list[str] = []
        same = _AMT_ANY.search(rest)
        if same and rest[same.end() :].strip() == "":
            amount = same.group(1)
            if rest[: same.start()].strip():
                desc_parts.append(rest[: same.start()].strip())
            i += 1
        else:
            if rest:
                desc_parts.append(rest)
            blob, amount, i = _collect_until_amount(lines, i + 1, desc_parts)
            desc_parts = [blob] if blob else []
        ops.append(
            {
                "hold": False,
                "date": posted,
                "code": code,
                "desc": " ".join(p for p in desc_parts if p).strip(),
                "amount": amount,
            }
        )
    return ops


def _collect_until_amount(
    lines: list[str], start: int, prefix: list[str]
) -> tuple[str, str, int]:
    i = start
    parts = list(prefix)
    amount = ""
    while i < len(lines):
        line = lines[i]
        if _START.match(line) or _HOLD.match(line):
            break
        only = _AMT_ONLY.match(line)
        if only:
            amount = only.group(1)
            i += 1
            break
        any_amt = _AMT_ANY.search(line)
        if any_amt and line[any_amt.end() :].strip() == "":
            amount = any_amt.group(1)
            head = line[: any_amt.start()].strip()
            if head:
                parts.append(head)
            i += 1
            break
        parts.append(line)
        i += 1
    return " ".join(p for p in parts if p).strip(), amount, i


def _op_to_tx(op: dict[str, str | bool]) -> ParsedTx | None:
    amount = parse_amount(str(op.get("amount") or ""))
    if amount is None or abs(amount) < 0.0001:
        return None
    posted = parse_datetime(str(op.get("date") or ""))
    if posted is None:
        return None
    desc = re.sub(r"\s+", " ", str(op.get("desc") or "")).strip()
    code = str(op.get("code") or "")
    mcc = _pick_mcc(desc)
    card = _card_tail(desc)
    merchant = _merchant(desc)
    category = category_for_mcc(mcc)
    if not category:
        category = _category_from_text(desc, amount)
    if not merchant:
        merchant = _short_desc(desc, code)

    needs, kind, internal = classify_review(category, desc, amount)
    blob = desc.lower()
    if any(m in blob for m in _OWN):
        needs, kind, internal = False, "transfer", True
        category = category or "Между своими"
    elif _IP_INCOME in blob:
        needs, kind, internal = False, "income", False
        category = "ИП"
    elif any(m in blob for m in _CASH_IN) or code.upper().startswith("CASHIN"):
        needs, kind, internal = False, ("income" if amount > 0 else "expense"), False
        category = "Наличные"
    elif any(m in blob for m in _CREDIT_PAY):
        needs, kind, internal = False, "expense", False
        category = "Кредит"
    elif mcc in {"6536", "6538", "4829", "6540"} or "card2card" in blob:
        needs, kind, internal = True, "transfer", False
        category = category or "Переводы"

    return ParsedTx(
        posted_at=posted,
        amount=amount,
        currency="RUB",
        category=category,
        description=merchant,
        mcc=mcc,
        card=card,
        status="",
        needs_review=needs,
        suggested_kind=kind,
        suggested_internal=internal,
        extra={"code": code, "raw": desc[:400]},
    )


def _pick_mcc(desc: str) -> str:
    found = [int(x) for x in _MCC.findall(desc)]
    if not found:
        return ""
    preferred = [c for c in found if c not in {3990, 3991}]
    code = preferred[-1] if preferred else found[-1]
    if code in {3990, 3991}:
        for inner in re.findall(r"\b(\d{4})\b", desc):
            n = int(inner)
            if n not in {3990, 3991} and category_for_mcc(n):
                return str(n)
    return str(code)


def _card_tail(desc: str) -> str:
    m = _CARD.search(desc)
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    return f"*{digits[-4:]}" if len(digits) >= 4 else m.group(1)


def _merchant(desc: str) -> str:
    m = re.search(r"место совершения операции:\s*(.+?)(?:MCC\d{4}|$)", desc, re.I)
    if m:
        place = m.group(1)
        parts = [p.strip() for p in re.split(r"[\\/>]", place) if p.strip()]
        if parts:
            name = re.sub(r"\s+", " ", parts[-1])
            name = re.sub(r"MCC\d{4}", "", name, flags=re.I).strip(" .")
            name = re.sub(r"\b\d{4}\b", "", name).strip(" .")
            return name[:80]
    return ""


def _short_desc(desc: str, code: str) -> str:
    if not desc:
        return code
    cut = desc
    cut = re.split(r"Без НДС|БЕЗ НДС", cut, maxsplit=1)[0].strip(" .")
    if len(cut) > 90:
        cut = cut[:87] + "…"
    return cut or code


def _category_from_text(desc: str, amount: float) -> str:
    blob = desc.lower()
    if "быстрых платежей" in blob or blob.startswith("перевод"):
        return "Переводы"
    if "оплата по договору" in blob:
        return "Оплата по договору"
    if "лотере" in blob:
        return "Развлечения"
    if amount > 0 and "перевод денежных средств" in blob:
        return "Переводы"
    return ""
