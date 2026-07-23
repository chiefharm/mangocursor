#!/bin/bash
cd /opt/mango-pipeline
DATE="${1:-2026-07-03}"
.venv/bin/python - <<PY
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
from site_lines import branch_label, is_tracked_call
from mango_vpbx import MangoVpbxClient

site = get_site("krasnoyarsk")
c = MangoVpbxClient(site.api_key, site.api_salt)
tz = ZoneInfo(site.tz_name)
y, m, d = map(int, "$DATE".split("-"))
day = datetime.date(y, m, d)
start = datetime.datetime(y, m, d, tzinfo=tz)
calls = [x for x in c.fetch_stats(int(start.timestamp()), int(start.timestamp()+86400-1), success=True)
           if datetime.datetime.fromtimestamp(x.start, tz).date() == day]
tracked = [x for x in calls if is_tracked_call("krasnoyarsk", x)]
rec = [x for x in tracked if x.recording_ids]
by_branch = collections.Counter(branch_label("krasnoyarsk", x) for x in rec)
print(f"Date {day}: total={len(calls)} tracked={len(tracked)} with_rec={len(rec)}")
for b, n in sorted(by_branch.items()):
    print(f"  {b}: {n}")
PY
