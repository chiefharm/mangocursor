#!/bin/bash
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
.venv/bin/python <<'PY'
import os
import datetime
from zoneinfo import ZoneInfo
from mango_vpbx import MangoVpbxClient, MangoVpbxError
from telegram_notify import parse_chat_ids, tg_broadcast_message

tz = ZoneInfo("Europe/Moscow")
c = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])

def direction(fr, to):
    if "sip:" in (to or "") and "sip:" not in (fr or ""):
        return "входящий"
    if "sip:" in (fr or "") and "sip:" not in (to or ""):
        return "исходящий"
    return "неизвестно"

def phone_of(call):
    if "sip:" in (call.to_number or ""):
        return (call.from_number or "").replace("sip:", "") or "?"
    return (call.to_number or "").replace("sip:", "") or "?"

lines = [
    "26 июня — 2 июля: расшифровок нет",
    "",
    "В Mango Office за эти дни записи разговоров не сохранены (поле records пустое). Без MP3 расшифровка невозможна.",
    "",
]

for y, m, d in [
    (2026, 6, 26), (2026, 6, 27), (2026, 6, 28),
    (2026, 6, 29), (2026, 6, 30), (2026, 7, 1), (2026, 7, 2),
]:
    label = f"{d:02d}.{m:02d}"
    day = datetime.datetime(y, m, d, tzinfo=tz)
    t = int(day.timestamp())
    try:
        calls = c.fetch_stats(t, t + 86400)
    except MangoVpbxError as e:
        lines.append(f"{label}: ошибка Mango API")
        continue
    rec = sum(1 for x in calls if x.recording_ids)
    lines.append(f"{label}: звонков {len(calls)}, с записью {rec}")
    for call in sorted(calls, key=lambda x: x.start):
        dt = datetime.datetime.fromtimestamp(call.start, tz).strftime("%H:%M")
        rec_mark = "запись" if call.recording_ids else "без записи"
        lines.append(f"  {dt} {direction(call.from_number, call.to_number)} {phone_of(call)} — {rec_mark}")

lines.extend([
    "",
    "Что сделать: в Mango Office включить запись входящих/исходящих на линии салона.",
    "После включения новые дни будут расшифровываться автоматически в 10:00 МСК.",
])

tg_broadcast_message(os.environ["TELEGRAM_BOT_TOKEN"], parse_chat_ids(), "\n".join(lines))
print("sent", len(lines), "lines")
PY
