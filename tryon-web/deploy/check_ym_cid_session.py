#!/usr/bin/env python3
import sqlite3
from pathlib import Path

CID = "1778157417318512003"
db = Path("/opt/soco-tryon/data/sessions.sqlite3")
print("db_exists", db.exists())
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute("PRAGMA table_info(sessions)")]
print("has_ym_cid", "ym_cid" in cols, "has_legacy", "yandex_client_id" in cols)

sql = """
SELECT token, phone, name, status, created_at, channel, ym_cid, return_url
FROM sessions
WHERE ym_cid = ?
ORDER BY created_at DESC
LIMIT 5
"""
rows = list(con.execute(sql, (CID,)))
print("matches", len(rows))
for r in rows:
    print(dict(r))

print("--- latest 5 ---")
for r in con.execute(
    "SELECT token, created_at, status, ym_cid, return_url FROM sessions ORDER BY created_at DESC LIMIT 5"
):
    print(dict(r))
