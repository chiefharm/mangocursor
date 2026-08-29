#!/usr/bin/env python3
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv("/opt/soco-tryon/.env")
KEY = os.environ["PERFECTCORP_API_KEY"].strip()
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
SRC = "https://cdn-st3.vigbo.com/u4872/4184/blog/6600354/6352418/83317460/1000-socokrsk-5a77162a7137e09cd269d4972965a5b8.jpg"
REF = "https://cdn-st3.vigbo.com/u4872/4184/blog/7788044/7696462/101183400/1000-socokrsk-53236db1146a38a982df7aabb4b6fef4.jpeg"

r = httpx.post(
    "https://yce-api-01.makeupar.com/s2s/v2.1/task/hair-transfer",
    headers=H,
    json={"src_file_url": SRC, "ref_file_url": REF},
    timeout=60,
)
print("submit", r.status_code, r.text[:200])
tid = r.json()["data"]["task_id"]
url = None
for i in range(30):
    time.sleep(3)
    g = httpx.get(
        f"https://yce-api-01.makeupar.com/s2s/v2.1/task/hair-transfer/{tid}",
        headers=H,
        timeout=30,
    )
    data = g.json().get("data") or {}
    st = data.get("task_status")
    print("poll", i, st)
    if st == "success":
        res = data.get("results") or {}
        url = res.get("url") if isinstance(res, dict) else None
        break
    if st in ("error", "failed"):
        print(data)
        break

if not url:
    raise SystemExit("no url")
img = httpx.get(url, timeout=90, follow_redirects=True)
Path("/tmp/youcam_compare.jpg").write_bytes(img.content)
print("saved", len(img.content))
