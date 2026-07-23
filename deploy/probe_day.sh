#!/bin/bash
set -e
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
DATE="${1:-2026-07-03}"
echo "=== HTML files for $DATE ==="
ls -la ${DATE}__*.html 2>/dev/null || echo "(none)"
echo "=== Mango calls ==="
.venv/bin/python - <<PY
import os, datetime
from zoneinfo import ZoneInfo
from mango_vpbx import MangoVpbxClient
y, m, d = map(int, "$DATE".split("-"))
tz = ZoneInfo("Europe/Moscow")
c = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])
day = datetime.datetime(y, m, d, tzinfo=tz)
t = int(day.timestamp())
calls = [x for x in c.fetch_stats(t, t + 86400 - 1, success=True)
           if datetime.datetime.fromtimestamp(x.start, tz).date() == day.date()]
inc = out = 0
for call in sorted(calls, key=lambda x: x.start):
    dt = datetime.datetime.fromtimestamp(call.start, tz).strftime("%H:%M:%S")
    rec = "REC" if call.recording_ids else "no-rec"
    fn, tn = call.from_number or "", call.to_number or ""
    if "sip:" in tn and "sip:" not in fn:
        inc += 1
        direction = "in"
    elif "sip:" in fn and "sip:" not in tn:
        out += 1
        direction = "out"
    else:
        direction = "?"
    print(f"{dt} {direction} {rec} dur={call.duration_sec}s {call.client_number}")
print(f"total={len(calls)} incoming={inc} outgoing={out} with_rec={sum(1 for x in calls if x.recording_ids)}")
PY
