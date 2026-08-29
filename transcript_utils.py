"""Shared transcript parsing, classification, and HTML helpers."""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ADMIN_GREETING = re.compile(
    r"администратор|я вас слушаю|салон красоты|добрый день.*слушаю",
    re.IGNORECASE,
)
ADMIN_LINE = re.compile(
    r"администратор|я вас слушаю|салон красоты|"
    r"пожалуйста.*хорошего дня|можно считать|полноценную стрижку|"
    r"ну есть это|записала вас|жд[её]м вас|на какое время",
    re.IGNORECASE,
)
CLIENT_LINE = re.compile(
    r"я вот|не нашл[аи].*сайт|хотел[аи]|подстричь|подровнять|челку|"
    r"скажите у вас|угу все понял|все поняла спасибо|перезвоню|подумаю",
    re.IGNORECASE,
)

_RU_ONES: Dict[str, int] = {
    "ноль": 0,
    "нуль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
}
_RU_TEENS: Dict[str, int] = {
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
}
_RU_TENS: Dict[str, int] = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
}

PATTERNS: List[Tuple[str, str]] = [
    (r"невозможно записаться|ошибка|не да[её]т|техподдерж|сбой", "Техсбой/онлайн-запись"),
    (r"сколько стоит|стоимость|цена|дорого", "Цена/риск потери"),
    (r"перезвоню|подумаю|пока просто отменим|не смогу", "Не закрыт в запись"),
    (r"отменить запись|перезаписаться|перенести|перенос", "Перенос/отмена"),
    (r"не устраивает|позднее время|пораньше|попозже", "Неудобное время"),
    (r"недовол|жалоб|претенз|извин", "Недовольство/жалоба"),
    (r"первый раз|ранее были", "Новый клиент"),
    (r"не делаем|отказ", "Отказ в услуге"),
]


def _words_to_int(fragment: str) -> Optional[int]:
    words = [w for w in re.split(r"\s+", fragment.strip().lower()) if w]
    if not words:
        return None
    total = 0
    i = 0
    while i < len(words):
        word = words[i]
        if word in _RU_TEENS:
            total += _RU_TEENS[word]
            i += 1
        elif word in _RU_TENS:
            total += _RU_TENS[word]
            i += 1
            if i < len(words) and words[i] in _RU_ONES:
                total += _RU_ONES[words[i]]
                i += 1
        elif word in _RU_ONES:
            total += _RU_ONES[word]
            i += 1
        else:
            return None
    return total


_RU_NUM_WORD = "|".join(
    sorted(set(_RU_ONES) | set(_RU_TEENS) | set(_RU_TENS), key=len, reverse=True)
)


def normalize_spoken_numbers(text: str) -> str:
    """Convert common spoken times and counts to digits (best effort)."""
    if not text:
        return text

    def spaced_time(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return match.group(0)

    text = re.sub(r"\b(\d{1,2})\s+0\s+0\b", spaced_time, text)

    def spoken_hour_zeros(match: re.Match[str]) -> str:
        hour = _words_to_int(match.group(1))
        if hour is not None and 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return match.group(0)

    text = re.sub(
        rf"\b(({_RU_NUM_WORD})(?:\s+({_RU_NUM_WORD}))?)\s+ноль\s+ноль\b",
        spoken_hour_zeros,
        text,
        flags=re.IGNORECASE,
    )

    def spoken_clock(match: re.Match[str]) -> str:
        hour = _words_to_int(match.group(1))
        minute = _words_to_int(match.group(2))
        if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return match.group(0)

    text = re.sub(
        r"\b((?:[а-яё]+)(?:\s+[а-яё]+)?)\s+((?:[а-яё]+)(?:\s+[а-яё]+)?)\b(?=\s+(?:и|на|к|в|у|до|после)\b|[,.!?]|$)",
        spoken_clock,
        text,
        flags=re.IGNORECASE,
    )

    def spoken_clock_anywhere(match: re.Match[str]) -> str:
        w2 = match.group(2).strip().lower()
        if re.match(r"^(час|минут|руб)", w2):
            return match.group(0)
        hour = _words_to_int(match.group(1))
        minute = _words_to_int(match.group(2))
        if hour is not None and minute is not None and 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return match.group(0)

    text = re.sub(
        rf"\b({_RU_NUM_WORD})\s+({_RU_NUM_WORD})\b",
        spoken_clock_anywhere,
        text,
        flags=re.IGNORECASE,
    )

    def spoken_with_unit(match: re.Match[str]) -> str:
        value = _words_to_int(match.group(1))
        if value is None:
            return match.group(0)
        return f"{value} {match.group(2)}"

    text = re.sub(
        r"\b((?:[а-яё]+)(?:\s+[а-яё]+)?)\s+(час(?:а|ов)?|минут(?:у|ы)?|руб(?:лей|ля)?)\b",
        spoken_with_unit,
        text,
        flags=re.IGNORECASE,
    )

    def spoken_word_to_digit(match: re.Match[str]) -> str:
        word = match.group(0).lower()
        if word in _RU_TEENS:
            return str(_RU_TEENS[word])
        if word in _RU_TENS:
            return str(_RU_TENS[word])
        if word in _RU_ONES:
            return str(_RU_ONES[word])
        return match.group(0)

    text = re.sub(rf"\b({_RU_NUM_WORD})\b", spoken_word_to_digit, text, flags=re.IGNORECASE)
    return text


def dedupe_segments(segments: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    seen: set[Tuple[str, str, str]] = set()
    out: List[Tuple[str, str, str]] = []
    for speaker, time_label, text in segments:
        key = (speaker, time_label, re.sub(r"\s+", " ", text.strip().lower()))
        if key in seen:
            continue
        seen.add(key)
        out.append((speaker, time_label, text.strip()))
    return out


def infer_admin_speaker(segments: List[Tuple[str, str, str]]) -> str:
    by_speaker: Dict[str, str] = {}
    for speaker, _, text in segments:
        by_speaker.setdefault(speaker, "")
        if len(by_speaker[speaker]) < 400:
            by_speaker[speaker] += " " + text
    for speaker, blob in by_speaker.items():
        if ADMIN_GREETING.search(blob):
            return speaker
    return segments[0][0] if segments else "Участник"


def classify_segment_role(text: str) -> Optional[str]:
    """Guess Администратор / Клиент from phrase content (mono-channel STT)."""
    if not text.strip():
        return None
    admin = len(ADMIN_LINE.findall(text))
    client = len(CLIENT_LINE.findall(text))
    if admin > client:
        return "Администратор"
    if client > admin:
        return "Клиент"
    return None


def apply_content_roles(segments: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    """Role assignment when Yandex did not split speakers (all one label)."""
    out: List[Tuple[str, str, str]] = []
    last_role = "Администратор"
    for _, time_label, text in segments:
        role = classify_segment_role(text)
        if role is None:
            role = "Клиент" if last_role == "Администратор" else "Администратор"
        last_role = role
        out.append((role, time_label, normalize_spoken_numbers(text)))
    return out


def apply_speaker_roles(segments: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    if not segments:
        return segments
    unique_speakers = {speaker for speaker, _, _ in segments}
    if len(unique_speakers) <= 1:
        return apply_content_roles(segments)
    admin = infer_admin_speaker(segments)
    return [
        (
            "Администратор" if speaker == admin else "Клиент",
            time_label,
            normalize_spoken_numbers(text),
        )
        for speaker, time_label, text in segments
    ]


def refine_segments(segments: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    """Dedupe + digit normalization only (no Администратор/Клиент labels)."""
    seen: set[tuple[str, str]] = set()
    out: List[Tuple[str, str, str]] = []
    for _, time_label, text in segments:
        normalized = normalize_spoken_numbers(text.strip())
        if not normalized:
            continue
        key = (time_label, normalized.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(("", time_label, normalized))
    return out


def transcript_paragraphs(transcript: List[Tuple[str, str]]) -> List[str]:
    """Plain lines for DOCX/Telegram — text only, numbers as digits."""
    lines: List[str] = []
    for _, text in transcript:
        line = normalize_spoken_numbers(text.strip())
        if line:
            lines.append(line)
    return lines



def parse_transcript_html(src: str, *, refine: bool = True) -> List[Tuple[str, str]]:
    rows = re.findall(
        r'<tr>\s*<td><strong>(.*?)</strong></td>.*?<td class="gray">\s*(.*?)\s*</td>.*?<td style="width: 70%">(.*?)</td>\s*</tr>',
        src,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not rows:
        rows = re.findall(
            r'<tr>\s*<td><strong>(.*?)</strong></td>.*?<td style="width: 70%">(.*?)</td>\s*</tr>',
            src,
            flags=re.IGNORECASE | re.DOTALL,
        )
        rows = [(speaker, "", text) for speaker, text in rows]

    segments: List[Tuple[str, str, str]] = []
    for speaker, time_label, text_block in rows:
        cleaned = re.sub(r"<br\s*/?>", "\n", text_block, flags=re.IGNORECASE)
        cleaned = re.sub(r"<.*?>", "", cleaned, flags=re.DOTALL)
        cleaned = html_lib.unescape(cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())
        if cleaned:
            segments.append((speaker.strip(), time_label.strip(), cleaned))

    if refine and segments:
        segments = refine_segments(segments)
    elif refine:
        return []

    return [("", text) for _, _, text in segments]


def parse_transcript_file(html_path: Path, *, refine: bool = True) -> List[Tuple[str, str]]:
    return parse_transcript_html(html_path.read_text(encoding="utf-8"), refine=refine)


def classify_text(raw: str) -> str | None:
    for pattern, category in PATTERNS:
        if re.search(pattern, raw, flags=re.IGNORECASE):
            return category
    return None


def classify_file(html_path: Path) -> str | None:
    return classify_text(html_path.read_text(encoding="utf-8"))


def extract_datetime(file_name: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})__(\d{2}-\d{2}-\d{2})__", file_name)
    if not match:
        return "unknown"
    date_part, time_part = match.groups()
    return f"{date_part} {time_part.replace('-', ':')}"


def format_mango_header_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%b.%Y %H:%M:%S")


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(max(seconds, 0), 60)
    return f"{minutes:02d}:{secs:02d} сек"


def build_transcript_html(
    *,
    call_dt: str,
    line_number: str,
    caller: str,
    callee: str,
    duration_sec: int,
    segments: List[Tuple[str, str, str]],
) -> str:
    """Build HTML in the same format as Mango LK export."""
    rows = [
        "    <tr style=\"line-height: 18px;\">",
        "        <td style=\"font-size: 14px;\"",
        f"            colspan=\"3\">Запись разговоров",
        f"            <strong>{html_lib.escape(call_dt)}</strong><br></td>",
        "    </tr>",
        "        <tr style=\"line-height: 18px;\">",
        "        <td style=\"width: 30%\" colspan=\"2\">Номер линии АТС:</td>",
        f"        <td style=\"width: 70%\"><strong>{html_lib.escape(line_number)}</strong></td>",
        "    </tr>",
        "        <tr style=\"line-height: 18px;\">",
        "        <td style=\"width: 30%\" colspan=\"2\">Кто звонил:</td>",
        f"        <td style=\"width: 70%\"><strong>{html_lib.escape(caller)}</strong></td>",
        "    </tr>",
        "    <tr style=\"line-height: 18px;\">",
        "        <td colspan=\"2\">С кем говорил:</td>",
        f"        <td><strong>{html_lib.escape(callee)}</strong></td>",
        "    </tr>",
        "    <tr style=\"line-height: 18px;\">",
        "        <td colspan=\"2\">Длительность:</td>",
        f"        <td><strong>{html_lib.escape(format_duration(duration_sec))}</strong><br></td>",
        "    </tr>",
    ]
    for _speaker, time_label, text in refine_segments(segments):
        text_html = html_lib.escape(text).replace("\n", "<br>\n                        ")
        rows.extend(
            [
                "        <tr>",
                "        <td><strong></strong></td>",
                "        <td class=\"gray\">",
                f"                {html_lib.escape(time_label)}",
                "        </td>",
                f"        <td style=\"width: 70%\">{text_html}<br>",
                "                        </td>",
                "    </tr>",
            ]
        )

    body = "\n".join(rows)
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ru">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <meta http-equiv="Content-Language" content="ru"/>
    <style type="text/css">
        td {{
            padding: 20px 15px 0 0;
            vertical-align: top;
        }}

        .gray {{
            color: gray;
        }}
    </style>
</head>
<body>
<table cellpadding="0" cellspacing="0">
    <tbody>
{body}
    </tbody>
</table>
</body>
</html>
"""


def call_file_name(start_ts: int, phone: str, extension_label: str) -> str:
    dt = datetime.fromtimestamp(start_ts)
    date_part = dt.strftime("%Y-%m-%d")
    time_part = dt.strftime("%H-%M-%S")
    safe_phone = re.sub(r"[^\d+]", "", phone or "unknown")
    safe_ext = re.sub(r"[^\wа-яА-ЯёЁ-]+", "", extension_label or "ext")
    return f"{date_part}__{time_part}__{safe_phone}__{safe_ext}.html"


def segments_from_webhook(payload: Dict) -> List[Tuple[str, str, str]]:
    """Try to normalize transcript segments from webhook / SA JSON."""
    candidates = [
        payload.get("transcript"),
        payload.get("transcription"),
        payload.get("dialog"),
        payload.get("text"),
    ]
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return [("Диалог", "", item.strip())]
        if isinstance(item, list):
            segments: List[Tuple[str, str, str]] = []
            for row in item:
                if not isinstance(row, dict):
                    continue
                speaker = str(row.get("speaker") or row.get("role") or row.get("channel") or "Участник")
                text = str(row.get("text") or row.get("phrase") or row.get("content") or "").strip()
                time_label = str(row.get("time") or row.get("offset") or row.get("start") or "")
                if text:
                    segments.append((speaker, time_label, text))
            if segments:
                return segments
    return []
