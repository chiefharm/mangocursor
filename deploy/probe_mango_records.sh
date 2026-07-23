#!/bin/bash
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
.venv/bin/python <<'PY'
import os, datetime, time
from zoneinfo import ZoneInfo
from mango_vpbx import MangoVpbxClient

c = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])
tz = ZoneInfo("Europe/Moscow")

for label, y, m, d in [("25.06", 2026, 6, 25), ("26.06", 2026, 6, 26), ("02.07", 2026, 7, 2)]:
    day = datetime.datetime(y, m, d, tzinfo=tz)
    t = int(day.timestamp())
    req = c.request_stats(t, t + 86400)
    key = req.get("key")
    csv = ""
    for _ in range(30):
        try:
            csv = c.get_stats_result(key)
            break
        except Exception as e:
            if "still processing" in str(e):
                time.sleep(2)
            else:
                print(label, "ERR", e)
                break
    print(f"\n===== {label} raw CSV (first 8 lines) =====")
    lines = csv.splitlines()[:8]
    for line in lines:
        print(line)
    calls = c.parse_stats_csv(csv)
    print(f"--- parsed {len(calls)} calls ---")
    for call in calls[:6]:
        dur = call.finish - call.start if call.finish and call.start else 0
        print(
            f"  entry={call.entry_id[:12]}.. dur={dur}s answer={call.answer} "
            f"records={call.raw.get('records', '')!r}"
        )
PY
