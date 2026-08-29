#!/usr/bin/env python3
import sqlite3
from pathlib import Path
p = Path("/opt/soco-tryon/data/sessions.sqlite3")
print("db_exists", p.exists())
if p.exists():
    c = sqlite3.connect(p)
    rows = list(c.execute(
        "select token,channel,phone,bot_user_id,unlocked_at,created_at from sessions order by created_at desc limit 8"
    ))
    for r in rows:
        print(r)
print("--- journal ---")
import subprocess
print(subprocess.check_output(
    ["journalctl", "-u", "soco-tryon", "--since", "40 min ago", "--no-pager", "-n", "60"],
    text=True,
)[-4000:])
