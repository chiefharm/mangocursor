#!/usr/bin/env python3
"""Verify Perfect Corp URL extract + one try-on against local uploads."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/opt/soco-tryon")

from app.perfectcorp import _extract_result_url  # noqa: E402

sample = Path("/tmp/pc_sample.json")
if sample.exists():
    data = json.loads(sample.read_text(encoding="utf-8"))
    url = _extract_result_url(data.get("data") or data)
    print("extract_ok", bool(url), (url or "")[:140])
else:
    print("no sample json")

import httpx

job = "0a2a7804f1e346639fee0ac9be002cc5"
base = Path(f"/opt/soco-tryon/data/uploads/{job}")
files = {
    "before": ("before.jpeg", base.joinpath("before.jpeg").read_bytes(), "image/jpeg"),
    "refs": ("ref_1.jpeg", base.joinpath("ref_1.jpeg").read_bytes(), "image/jpeg"),
}
print("posting tryon…")
r = httpx.post("http://127.0.0.1:8088/api/tryon", files=files, timeout=300)
print("status", r.status_code)
print(r.text[:2000])
