#!/usr/bin/env python3
import json
import os
import ssl
import urllib.request
from pathlib import Path


def load(p: str) -> None:
    path = Path(p)
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load("/opt/soco-tryon/.env")
load("/opt/mango-pipeline/.env")

tg = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tg}/getMe"), timeout=30) as r:
    d = json.load(r)
print("TG_USER", (d.get("result") or {}).get("username"))

mx = os.environ.get("MAX_BOT_TOKEN", "").strip().strip('"')
ctx = ssl._create_unverified_context()
for path in ("/me", "/bots"):
    try:
        req = urllib.request.Request(f"https://platform-api2.max.ru{path}", headers={"Authorization": mx})
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            print("MAX", path, r.read()[:500].decode("utf-8", errors="replace"))
    except Exception as e:
        print("MAX", path, type(e).__name__, e)
