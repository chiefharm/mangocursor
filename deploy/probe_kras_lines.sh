#!/bin/bash
cd /opt/mango-pipeline
.venv/bin/python - <<'PY'
import os, datetime, collections
from pathlib import Path
from zoneinfo import ZoneInfo

def load_dotenv(path):
    for raw in Path(".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv(Path(".env"))
from site_config import get_site
from mango_vpbx import MangoVpbxClient

site = get_site("krasnoyarsk")
c = MangoVpbxClient(site.api_key, site.api_salt)
tz = ZoneInfo(site.tz_name)
day = datetime.date(2026, 7, 3)
start = datetime.datetime(day.year, day.month, day.day, tzinfo=tz)
calls = [
    x
    for x in c.fetch_stats(int(start.timestamp()), int(start.timestamp() + 86400 - 1), success=True)
    if datetime.datetime.fromtimestamp(x.start, tz).date() == day
]
rec_calls = [x for x in calls if x.recording_ids]
by_line = collections.Counter(x.line_number for x in rec_calls)
by_to = collections.Counter(x.to_number for x in rec_calls)
print(f"calls with recording: {len(rec_calls)}")
print(f"\nline_number ({len(by_line)} unique):")
for k, v in by_line.most_common():
    print(f"  {k}: {v}")
print(f"\nto_number ({len(by_to)} unique):")
for k, v in by_to.most_common():
    print(f"  {k}: {v}")
PY
