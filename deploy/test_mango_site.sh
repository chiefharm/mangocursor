#!/bin/bash
set -e
cd /opt/mango-pipeline
SITE="${1:-krasnoyarsk}"
.venv/bin/python - <<PY
import os, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def load_dotenv(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

load_dotenv(Path(".env"))
from site_config import get_site
from mango_vpbx import MangoVpbxClient

site = get_site("$SITE")
print(f"Site: {site.site_id} — {site.label} (ЛС {site.account})")
c = MangoVpbxClient(site.api_key, site.api_salt)
tz = ZoneInfo(site.tz_name)
day = datetime.datetime.now(tz).date() - datetime.timedelta(days=1)
start = datetime.datetime(day.year, day.month, day.day, tzinfo=tz)
t = int(start.timestamp())
calls = c.fetch_stats(t, t + 86400 - 1, success=True)
day_calls = [x for x in calls if datetime.datetime.fromtimestamp(x.start, tz).date() == day]
rec = sum(1 for x in day_calls if x.recording_ids)
lines = sorted({x.line_number for x in day_calls if x.line_number})
print(f"Yesterday {day}: calls={len(day_calls)} with_rec={rec}")
if lines:
    print("line_number(s):", ", ".join(lines[:3]))
    if not os.getenv(f"SITE_{site.site_id.upper()}_LINE_NUMBER"):
        print(f"[HINT] set SITE_{site.site_id.upper()}_LINE_NUMBER={lines[0]!r}")
print("[OK] Mango API works")
PY
