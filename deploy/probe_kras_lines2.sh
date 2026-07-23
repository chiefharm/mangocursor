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

def is_incoming(call):
    fn, tn = call.from_number or "", call.to_number or ""
    return "sip:" in tn and "sip:" not in fn

incoming = [x for x in calls if is_incoming(x)]
print(f"total={len(calls)} incoming={len(incoming)}")

for label, key in [
    ("line_number", lambda x: x.line_number or "(empty)"),
    ("to_number sip", lambda x: x.to_number if "sip:" in (x.to_number or "") else None),
    ("to_extension", lambda x: x.to_extension or None),
    ("from_extension", lambda x: x.from_extension or None),
]:
    ctr = collections.Counter()
    for x in incoming:
        val = key(x)
        if val:
            ctr[val] += 1
    print(f"\n{label} ({len(ctr)} unique, incoming only):")
    for k, v in ctr.most_common(15):
        print(f"  {k}: {v}")
PY
