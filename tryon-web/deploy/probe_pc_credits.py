#!/usr/bin/env python3
import json
import urllib.request

k = ""
for line in open("/opt/soco-tryon/.env", encoding="utf-8"):
    if line.startswith("PERFECTCORP_API_KEY="):
        k = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
print("key_set", bool(k), "len", len(k))
for path in ("/s2s/v1.0/client/credit", "/s2s/v2.0/credit/feature-cost"):
    req = urllib.request.Request(
        "https://yce-api-01.makeupar.com" + path,
        headers={"Authorization": "Bearer " + k},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
        print("===", path)
        print(raw[:3500])
    except Exception as e:
        print("FAIL", path, e)
