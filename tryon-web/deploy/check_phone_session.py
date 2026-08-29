#!/usr/bin/env python3
import sqlite3
from pathlib import Path

PHONE_HINTS = ("79050874245", "+79050874245", "9050874245")
paths = [
    Path("/opt/soco-tryon/data/sessions.sqlite3"),
    Path("/opt/soco-tryon/data/clients.sqlite3"),
]
for db in paths:
    print(f"\n=== {db} exists={db.exists()} ===")
    if not db.exists():
        continue
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("tables", tables)
    for table in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        phone_cols = [c for c in cols if "phone" in c.lower() or c in ("ym_cid", "token", "client_id")]
        if not any("phone" in c.lower() for c in cols):
            continue
        print(f"-- {table} cols={cols}")
        for hint in PHONE_HINTS:
            # loose match
            q = f"SELECT * FROM {table} WHERE phone LIKE ? ORDER BY 1 DESC LIMIT 5"
            try:
                rows = list(con.execute(q, (f"%{hint[-10:]}%",)))
            except Exception as e:
                print("err", e)
                continue
            if rows:
                print(f"hint={hint} matches={len(rows)}")
                for r in rows:
                    print(dict(r))

# also exact ym_cid session again with phone context
con = sqlite3.connect("/opt/soco-tryon/data/sessions.sqlite3")
con.row_factory = sqlite3.Row
print("\n=== session by ym_cid ===")
for r in con.execute(
    "SELECT * FROM sessions WHERE ym_cid=? OR phone LIKE ?",
    ("1778157417318512003", "%9050874245%"),
):
    print(dict(r))
