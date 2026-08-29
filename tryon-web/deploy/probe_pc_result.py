#!/usr/bin/env python3
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv("/opt/soco-tryon/.env")
KEY = os.environ["PERFECTCORP_API_KEY"].strip()
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
src = "https://cdn-st3.vigbo.com/u4872/4184/blog/6600354/6352418/83317460/1000-socokrsk-5a77162a7137e09cd269d4972965a5b8.jpg"
ref = "https://cdn-st3.vigbo.com/u4872/4184/blog/7788044/7696462/101183400/1000-socokrsk-53236db1146a38a982df7aabb4b6fef4.jpeg"

r = httpx.post(
    "https://yce-api-01.makeupar.com/s2s/v2.1/task/hair-transfer",
    headers=H,
    json={"src_file_url": src, "ref_file_url": ref},
    timeout=60,
)
print("submit", r.status_code, r.text[:300])
tid = r.json()["data"]["task_id"]
for i in range(25):
    time.sleep(3)
    g = httpx.get(
        f"https://yce-api-01.makeupar.com/s2s/v2.1/task/hair-transfer/{tid}",
        headers=H,
        timeout=30,
    )
    data = g.json()
    st = (data.get("data") or {}).get("task_status")
    print("poll", i, st, json.dumps(data, ensure_ascii=False)[:500])
    if st in ("success", "error", "Success", "Error"):
        Path("/tmp/pc_sample.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        break
print("done")
