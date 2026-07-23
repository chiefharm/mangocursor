#!/usr/bin/env python3
"""Probe Moscow Mango stats for one day."""
import datetime
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from mango_vpbx import MangoVpbxClient


def load_dotenv(path: Path) -> None:
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


def main() -> None:
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-07-07"
    base = Path("/opt/mango-pipeline")
    load_dotenv(base / ".env")
    key = os.environ.get("MANGO_VPBX_API_KEY", "").strip()
    salt = os.environ.get("MANGO_VPBX_API_SALT", "").strip()
    if not key or not salt:
        raise SystemExit("MANGO_VPBX_API_KEY/SALT missing")

    y, m, d = map(int, date_str.split("-"))
    tz = ZoneInfo("Europe/Moscow")
    day = datetime.datetime(y, m, d, tzinfo=tz)
    t = int(day.timestamp())
    client = MangoVpbxClient(key, salt)
    calls = [
        x
        for x in client.fetch_stats(t, t + 86400 - 1)
        if datetime.datetime.fromtimestamp(x.start, tz).date() == day.date()
    ]
    inc = out = 0
    for call in sorted(calls, key=lambda x: x.start):
        fn, tn = call.from_number or "", call.to_number or ""
        if "sip:" in tn and "sip:" not in fn:
            inc += 1
            direction = "in"
        elif "sip:" in fn and "sip:" not in tn:
            out += 1
            direction = "out"
        else:
            direction = "?"
        rec = "REC" if call.recording_ids else "no-rec"
        dt = datetime.datetime.fromtimestamp(call.start, tz).strftime("%H:%M:%S")
        print(f"{dt} {direction} {rec} dur={call.duration_sec}s {call.client_number}")
    print(
        f"total={len(calls)} incoming={inc} outgoing={out} "
        f"with_rec={sum(1 for x in calls if x.recording_ids)}"
    )


if __name__ == "__main__":
    main()
