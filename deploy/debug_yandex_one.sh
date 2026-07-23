#!/bin/bash
set -euo pipefail
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
.venv/bin/python <<'PY'
import os, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from mango_vpbx import MangoVpbxClient
from yandex_stt import client_from_env
from mango_sync import transcript_from_yandex

tz = ZoneInfo("Europe/Moscow")
start = datetime.datetime(2026, 6, 26, 0, 0, tzinfo=tz)
c = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])
calls = [x for x in c.fetch_stats(int(start.timestamp()), int(start.timestamp() + 86400), True) if x.recording_ids]
print(f"calls with recording: {len(calls)}")
if not calls:
    raise SystemExit(0)
call = calls[0]
print(f"entry={call.entry_id} dur={call.duration_sec} rec={call.recording_ids}")
yc = client_from_env()
try:
    segs = transcript_from_yandex(c, yc, call, Path("/opt/mango-pipeline/data/yandex_cache"))
    print(f"OK segments={len(segs)}")
except Exception as e:
    print(f"FAIL: {e}")
PY
