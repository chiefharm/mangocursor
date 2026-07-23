#!/bin/bash
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
.venv/bin/python <<'PY'
import os, datetime
from zoneinfo import ZoneInfo
from mango_vpbx import MangoVpbxClient

tz = ZoneInfo("Europe/Moscow")
c = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])
for y, m, d in [
    (2026, 6, 25), (2026, 6, 26), (2026, 6, 27), (2026, 6, 28),
    (2026, 6, 29), (2026, 6, 30), (2026, 7, 1), (2026, 7, 2),
]:
    day = datetime.datetime(y, m, d, tzinfo=tz)
    t = int(day.timestamp())
    try:
        calls = c.fetch_stats(t, t + 86400)
    except Exception as e:
        print(f"{y}-{m:02d}-{d:02d} ERROR {e}")
        continue
    rec = sum(1 for x in calls if x.recording_ids)
    print(f"{y}-{m:02d}-{d:02d} total={len(calls)} with_recording={rec}")
PY
