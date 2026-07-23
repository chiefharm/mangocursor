"""Telegram message formatting for call QC reports."""

from __future__ import annotations

from datetime import datetime

from call_qc import CallAssessment, Verdict

_MONTHS_RU = (
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


def format_date_no_year(date_str: str) -> str:
    """YYYY-MM-DD -> «25 июня»."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day} {_MONTHS_RU[dt.month]}"


def format_time_short(time_hms: str) -> str:
    """HH:MM:SS or HH:MM -> HH:MM."""
    parts = time_hms.strip().split(":")
    if len(parts) >= 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return time_hms


def salon_risk(category: str, verdict: Verdict) -> str:
    """Какие риски несёт салон в этом звонке."""
    c = category.lower()
    if "недовол" in c or "жалоб" in c:
        return (
            "Репутационный риск: недовольный клиент может уйти к конкурентам "
            "и оставить негативный отзыв."
        )
    if "техсбой" in c:
        return (
            "Потеря заявки и доверия к онлайн-записи: клиент не смог записаться "
            "и ушёл без помощи администратора."
        )
    if "отказ" in c:
        return "Клиент уходит без альтернативы — риск потери и негатива."
    if "цена" in c:
        return (
            "Риск потери на этапе цены: клиент узнал стоимость, "
            "но не был дожат до конкретной записи."
        )
    if "справка" in c or "ушёл без" in c:
        return (
            "Потеря лида: клиент интересовался услугой, "
            "но ушёл без записи на приём."
        )
    if "не дожали" in c or "не записали" in c:
        return "Упущенная выручка: был интерес к услуге, запись не оформлена."
    if "перенос" in c or "перезвон" in c or "обещали" in c:
        return (
            "Риск no-show: время не зафиксировано в звонке — "
            "клиент может не прийти или уйти к конкуренту."
        )
    if "требует проверки" in c:
        return "Исход неясен — возможна потеря клиента без дожима и перезвона."
    if verdict == "uncertain":
        return (
            "Исход звонка не подтверждён — есть риск потерять клиента, "
            "если не перезвонить и не зафиксировать запись."
        )
    return "Звонок требует контроля качества — возможна потеря клиента или выручки."


def build_call_message(
    assessment: CallAssessment,
    *,
    date_str: str,
    time_hms: str,
    direction: str,
    phone: str,
    site_label: str = "",
    branch: str = "",
) -> str:
    """Короткое сообщение в Telegram без цитат из диалога."""
    date_fmt = format_date_no_year(date_str)
    time_fmt = format_time_short(time_hms)
    prefix = assessment.doubt_prefix

    lines = [
        f"{date_fmt} · {time_fmt}",
        f"{direction} · {phone}",
    ]
    if branch:
        lines.append(f"Точка: {branch}")
    lines.extend(
        [
            f"{prefix}Категория: {assessment.category}",
            "",
            f"Ошибка: {assessment.comment}",
            "",
            "Проблема:",
            salon_risk(assessment.category, assessment.verdict),
        ]
    )
    body = "\n".join(lines)
    if site_label:
        return f"{site_label}\n\n{body}"
    return body
