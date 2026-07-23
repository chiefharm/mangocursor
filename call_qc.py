"""Call quality control: decide which transcripts to send to the owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Literal, Tuple

Verdict = Literal["good", "bad", "uncertain"]


@dataclass(frozen=True)
class CallAssessment:
    verdict: Verdict
    category: str
    comment: str
    booking_confirmed: bool

    @property
    def should_send(self) -> bool:
        return self.verdict in ("bad", "uncertain")

    @property
    def doubt_prefix(self) -> str:
        if self.verdict == "uncertain":
            return "⚠️ Сомнение: "
        return ""


BOOKING_CONFIRMED_RE = re.compile(
    r"записал[аиоы]?|записываю|записан[аоы]?|оформил[аи]?|"
    r"жд[её]м вас|до встречи|подтверждаю|ваша запись|"
    r"перенес[уё]\s+ваш|переношу\s+ваш|запись\s+на\s+\d|"
    r"запись\s+перенес|согласовано\s+на|будем\s+вас\s+ждать",
    re.IGNORECASE,
)

EXISTING_APPOINTMENT_RE = re.compile(
    r"записан[ыа]?|у нас запись|мы записан|наша запись|"
    r"приедем|подъедем|у меня запись|запись к вам|у меня запись к",
    re.IGNORECASE,
)

DISSATISFACTION_RE = re.compile(
    r"недовол|жалоб|претенз|возмущ|плохо обслуж|кошмар|ужас|обидно",
    re.IGNORECASE,
)

NO_CLOSE_RE = re.compile(
    r"перезвоню|перезвоните|подумаю|надо подумать|пока не знаю|"
    r"не смогу|нет мест|не можем принять|не сможем вас принять",
    re.IGNORECASE,
)

PRICE_RE = re.compile(r"сколько стоит|стоимость|цена|прайс|дорого", re.IGNORECASE)

INQUIRY_RE = re.compile(
    r"есть ли|можно ли|подскажите|хотела узнать|интересует|"
    r"не нашла вас|хотела бы|можно записаться|хотел[аи] записаться",
    re.IGNORECASE,
)

THANKS_LEAVE_RE = re.compile(
    r"спасибо.*(до свидания|хорошего дня)|"
    r"(до свидания|хорошего дня).*спасибо|"
    r"все поняла.*спасибо|понял[аи]?\s+спасибо|угу\s+все\s+поняла",
    re.IGNORECASE,
)

TECH_FAIL_RE = re.compile(
    r"невозможно записаться|ошибка|техподдерж|сбой|не да[её]т записаться",
    re.IGNORECASE,
)

REFUSAL_RE = re.compile(r"не делаем|отказ", re.IGNORECASE)

ADMIN_CALLBACK_RE = re.compile(
    r"переговорю|напишу вам|перезвоню|свяжусь|уточню и",
    re.IGNORECASE,
)

TIME_AGREED_RE = re.compile(
    r"\d{1,2}:\d{2}.{0,50}(ладно|договорились|хорошо|спасибо|угу)|"
    r"(ладно|хорошо|договорились).{0,50}\d{1,2}:\d{2}|"
    r"запись\s+на\s+\d{1,2}:\d{2}",
    re.IGNORECASE,
)

RESCHEDULE_OK_RE = re.compile(
    r"перенес[уё]|переношу|не критично|жд[её]м вас|согласован",
    re.IGNORECASE,
)


def _dialog_text(transcript: List[Tuple[str, str]]) -> str:
    return " ".join(text for _, text in transcript)


def _role_text(transcript: List[Tuple[str, str]], role: str) -> str:
    return " ".join(text for speaker, text in transcript if speaker == role)


def assess_call(transcript: List[Tuple[str, str]]) -> CallAssessment:
    if not transcript:
        return CallAssessment(
            "uncertain",
            "Пустая расшифровка",
            "Нет текста для анализа.",
            False,
        )

    full = _dialog_text(transcript)
    client = _role_text(transcript, "Клиент") or full
    admin = _role_text(transcript, "Администратор") or full
    booking = bool(BOOKING_CONFIRMED_RE.search(full))
    existing = bool(EXISTING_APPOINTMENT_RE.search(full))
    thanks_leave = bool(THANKS_LEAVE_RE.search(full))

    if DISSATISFACTION_RE.search(full):
        return CallAssessment(
            "bad",
            "Недовольство клиента",
            "Клиент недоволен — нужен разбор и ответ администрации.",
            booking,
        )

    if TECH_FAIL_RE.search(full):
        return CallAssessment(
            "bad",
            "Техсбой записи",
            "Проблема с записью/системой — клиента не оформили в звонке.",
            booking,
        )

    if REFUSAL_RE.search(full) and not booking:
        return CallAssessment(
            "bad",
            "Отказ в услуге",
            "Отказ без понятной альтернативы или записи.",
            booking,
        )

    if existing and ADMIN_CALLBACK_RE.search(admin) and not TIME_AGREED_RE.search(full):
        return CallAssessment(
            "uncertain",
            "Перенос без фиксации",
            "Есть запись, но админ ушёл уточнять — в звонке нет финального подтверждения.",
            False,
        )

    if TIME_AGREED_RE.search(full):
        return CallAssessment(
            "good",
            "Запись оформлена",
            "Время согласовано, клиент записан.",
            True,
        )

    if booking and thanks_leave:
        return CallAssessment(
            "good",
            "Запись оформлена",
            "Клиент записан или время подтверждено.",
            True,
        )

    if existing and re.search(r"пробк|опозд|попозже|задерж", full, re.IGNORECASE):
        if RESCHEDULE_OK_RE.search(admin) or booking:
            return CallAssessment(
                "good",
                "Ок: опоздание по записи",
                "Клиент уже записан, админ согласовал опоздание.",
                True,
            )

    if existing and re.search(r"перенести|перенос|разбить", full, re.IGNORECASE):
        if TIME_AGREED_RE.search(full) or booking:
            return CallAssessment(
                "good",
                "Ок: перенос согласован",
                "Перенос/новое время согласованы.",
                True,
            )
        if ADMIN_CALLBACK_RE.search(admin):
            return CallAssessment(
                "uncertain",
                "Перенос без фиксации",
                "Обсуждали перенос, но в звонке нет чёткого подтверждения записи.",
                False,
            )

    if PRICE_RE.search(full) and not booking:
        if thanks_leave:
            return CallAssessment(
                "bad",
                "Цена без записи",
                "Спросили цену, поблагодарили и ушли без записи.",
                False,
            )
        return CallAssessment(
            "uncertain",
            "Цена — исход неясен",
            "Обсуждали стоимость — непонятно, записали ли клиента.",
            False,
        )

    if INQUIRY_RE.search(client) and not booking and not existing:
        if thanks_leave:
            return CallAssessment(
                "bad",
                "Справка без записи",
                "Клиент спросил информацию и ушёл без записи.",
                False,
            )

    if NO_CLOSE_RE.search(full) and not booking and not existing and not TIME_AGREED_RE.search(full):
        return CallAssessment(
            "bad",
            "Не дожали до записи",
            "Клиент не записан: отложил решение, отказ или нет свободных мест.",
            False,
        )

    if ADMIN_CALLBACK_RE.search(admin) and not booking:
        return CallAssessment(
            "uncertain",
            "Обещали перезвонить",
            "Админ обещал уточнить/перезвонить — в звонке записи нет.",
            False,
        )

    if re.search(r"первый раз|хотел[аи] записаться|запишите|можно на ", full, re.IGNORECASE):
        if not booking:
            return CallAssessment(
                "bad",
                "Не записали клиента",
                "Был запрос на запись, подтверждения в разговоре нет.",
                False,
            )

    if booking:
        return CallAssessment(
            "good",
            "Запись оформлена",
            "Клиент записан или время подтверждено.",
            True,
        )

    if thanks_leave and len(full) < 350:
        return CallAssessment(
            "bad",
            "Ушёл без записи",
            "Короткий звонок: клиент поблагодарил и не записался.",
            False,
        )

    if len(full) > 120:
        return CallAssessment(
            "uncertain",
            "Требует проверки",
            "Не уверен, хорошо ли отработан звонок — нужна ваша оценка.",
            False,
        )

    return CallAssessment(
        "good",
        "Норма",
        "Признаков косяка не найдено.",
        booking,
    )


def format_day_summary(
    date_str: str,
    incoming: int,
    outgoing: int,
    analyzed: int,
    sent_bad: int,
    sent_uncertain: int,
    *,
    site_label: str = "",
    stats_unavailable: bool = False,
) -> str:
    """Build day summary. If stats_unavailable, use HTML (parse_mode=HTML in Telegram)."""
    import html as html_lib

    months = (
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    try:
        y, m, d = map(int, date_str.split("-"))
        date_label = f"{d} {months[m]}"
    except (ValueError, IndexError):
        date_label = date_str

    if stats_unavailable:
        # Telegram has no font color; 🔴 + bold is the strongest visual cue.
        lines = [
            f"Отчёт за {html_lib.escape(date_label)}",
            "<b>🔴 Статистика недоступна</b>",
            "Mango не отдал данные (часто: минус на балансе / лимит API).",
            f"Расшифровок проанализировано: {analyzed}",
            f"Косячных на проверку: {sent_bad + sent_uncertain}",
        ]
    else:
        lines = [
            f"Отчёт за {date_label}",
            f"Входящих: {incoming}",
            f"Исходящих: {outgoing}",
            f"Расшифровок проанализировано: {analyzed}",
            f"Косячных на проверку: {sent_bad + sent_uncertain}",
        ]
    if sent_uncertain:
        lines.append(f"Из них сомнительных: {sent_uncertain}")
    if sent_bad:
        lines.append(f"Явно проблемных: {sent_bad}")
    body = "\n".join(lines)
    if site_label:
        label = html_lib.escape(site_label) if stats_unavailable else site_label
        return f"{label}\n\n{body}"
    return body
