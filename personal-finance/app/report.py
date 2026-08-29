"""Human-readable money digest for the site and Telegram."""

from __future__ import annotations

from datetime import date
from typing import Any

_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_MONTHS_NOM = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def money(n: float) -> str:
    sign = "−" if n < 0 else ""
    body = f"{abs(n):,.2f}".replace(",", " ").replace(".", ",")
    if body.endswith(",00"):
        body = body[:-3]
    return f"{sign}{body} ₽"


def signed_money(n: float) -> str:
    if n > 0:
        return f"+{money(n)}"
    if n < 0:
        return money(n)
    return money(0)


def format_day(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {_MONTHS[d.month]}"


def format_period(date_from: str, date_to: str) -> str:
    a = date.fromisoformat(date_from[:10])
    b = date.fromisoformat(date_to[:10])
    if a == b:
        return format_day(date_from)
    if a.year == b.year and a.month == b.month:
        return f"{a.day}–{b.day} {_MONTHS[a.month]}"
    if a.year == b.year:
        return f"{a.day} {_MONTHS[a.month]} — {b.day} {_MONTHS[b.month]}"
    return f"{format_day(date_from)} {a.year} — {format_day(date_to)} {b.year}"


def month_title(year: int, month: int) -> str:
    name = _MONTHS_NOM[month]
    return f"{name[:1].upper()}{name[1:]} {year}"


def delta_phrase(current: float, previous: float, *, invert: bool = False) -> str:
    diff = current - previous
    if abs(diff) < 0.5:
        return "без изменений"
    word = "больше" if diff > 0 else "меньше"
    if invert:
        word = "больше" if diff > 0 else "меньше"
    return f"{word} на {money(abs(diff))}"


def telegram_import_message(
    *,
    filename: str,
    imported: dict[str, Any],
    summary: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> str:
    period = format_period(summary["period"]["from"], summary["period"]["to"])
    lines = [
        "<b>Личные финансы</b>",
        f"Выписка {period}",
        f"Новых операций: {imported['new_count']}"
        + (f" · дубликаты: {imported['dup_count']}" if imported.get("dup_count") else ""),
        "",
        f"Доходы: <b>{money(summary['income'])}</b>",
        f"Расходы: <b>{money(summary['expense'])}</b>",
        f"Сальдо: <b>{signed_money(summary['net'])}</b>",
    ]
    if previous:
        lines.append("")
        lines.append(
            "К прошлому периоду: доходы "
            + delta_phrase(summary["income"], previous["income"])
            + ", расходы "
            + delta_phrase(summary["expense"], previous["expense"])
        )
    cats = summary.get("expense_by_category") or []
    if cats:
        lines.append("")
        lines.append("Расходы по статьям:")
        for row in cats[:12]:
            lines.append(f"• {row['name']} — {money(row['amount'])}")
    income_cats = summary.get("income_by_category") or []
    if income_cats:
        lines.append("")
        lines.append("Доходы:")
        for row in income_cats[:8]:
            lines.append(f"• {row['name']} — {money(row['amount'])}")
    n_review = int(summary.get("unreviewed_count") or 0)
    if n_review:
        lines.append("")
        lines.append(
            f"Нужно пояснить: <b>{n_review}</b> "
            + _plural(n_review, "перевод", "перевода", "переводов")
            + " без статьи"
        )
        if summary.get("unreviewed_sum"):
            lines.append(f"Сумма неразнесённых: {money(abs(summary['unreviewed_sum']))}")
    return "\n".join(lines)


def telegram_reviewed_message(summary: dict[str, Any]) -> str:
    period = format_period(summary["period"]["from"], summary["period"]["to"])
    lines = [
        "<b>Личные финансы</b> · все переводы разнесены",
        period,
        "",
        f"Доходы: <b>{money(summary['income'])}</b>",
        f"Расходы: <b>{money(summary['expense'])}</b>",
        f"Сальдо: <b>{signed_money(summary['net'])}</b>",
    ]
    cats = summary.get("expense_by_category") or []
    if cats:
        lines.append("")
        for row in cats[:12]:
            lines.append(f"• {row['name']} — {money(row['amount'])}")
    return "\n".join(lines)


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return many
    n = n % 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def telegram_pending_message(
    *,
    imported: dict[str, Any],
    summary: dict[str, Any],
    site_url: str = "",
) -> str:
    n = int(summary.get("unreviewed_count") or 0)
    lines = [
        "<b>Касса</b> · выписка загружена",
        f"Новых операций: {imported.get('new_count') or 0}"
        + (f" · дубликаты: {imported.get('dup_count')}" if imported.get("dup_count") else ""),
        "",
        f"Нужно пояснить <b>{n}</b> "
        + _plural(n, "перевод", "перевода", "переводов")
        + " без статьи"
        + (
            f" ({money(abs(float(summary.get('unreviewed_sum') or 0)))})"
            if summary.get("unreviewed_sum")
            else ""
        ),
        "Итоги, всплески и советы по цели пришлю, когда разнесёте переводы.",
    ]
    if site_url:
        lines.append(site_url)
    return "\n".join(lines)


def telegram_digest_message(digest: Any) -> str:
    from .advice import Digest

    if not isinstance(digest, Digest):
        digest = Digest.from_dict(digest)
    period = format_period(digest.period_from, digest.period_to)
    lines = [
        "<b>Касса</b> · итоги выписки",
        period,
        "",
        f"Доходы: <b>{money(digest.income)}</b>",
        f"Расходы: <b>{money(digest.expense)}</b>",
        f"Сальдо: <b>{signed_money(digest.net)}</b>",
    ]
    if digest.goal_amount is not None:
        lines.append(f"Цель (сальдо): <b>{money(digest.goal_amount)}</b>")
        if digest.gap is None:
            pass
        elif digest.gap > 0:
            lines.append(f"До цели не хватает <b>{money(digest.gap)}</b>")
        else:
            lines.append(f"Цель выполнена, запас {money(abs(digest.gap))}")
    else:
        lines.append("Цель не задана — /цель 80000")
    if digest.spikes:
        lines.append("")
        lines.append("Сильно выросли:")
        for spike in digest.spikes[:5]:
            was = f"было {money(spike.previous)}" if spike.previous else "раньше не было"
            lines.append(
                f"• {spike.name} — {money(spike.current)} ({was}, +{money(spike.diff)})"
            )
    if digest.recs:
        lines.append("")
        lines.append("Как дотянуть цель:")
        for i, rec in enumerate(digest.recs, 1):
            lines.append(f"{i}. {rec.text}")
    return "\n".join(lines)


def digest_keyboard(digest_id: int, digest: Any) -> dict[str, Any]:
    from .advice import Digest

    if not isinstance(digest, Digest):
        digest = Digest.from_dict(digest)
    rows: list[list[dict[str, str]]] = []
    for i, spike in enumerate(digest.spikes[:2]):
        short = spike.name if len(spike.name) <= 16 else spike.name[:14] + "…"
        rows.append(
            [
                {"text": f"{short}: норма", "callback_data": f"fb:{digest_id}:{i}:n"},
                {"text": "сократить", "callback_data": f"fb:{digest_id}:{i}:c"},
                {"text": "не расход", "callback_data": f"fb:{digest_id}:{i}:x"},
            ]
        )
    rows.append(
        [
            {"text": "Цель ок", "callback_data": "goal:ok"},
            {"text": "Другая цель", "callback_data": "goal:edit"},
        ]
    )
    return {"inline_keyboard": rows}
