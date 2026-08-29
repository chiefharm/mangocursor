#!/usr/bin/env python3
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv("/opt/soco-tryon/.env")

from app.watermark import apply_watermark
from app.max_client import lead_targets, send_text

results = sorted(Path("/opt/soco-tryon/data/results").glob("*/after_*.jpg"))
if results:
    p = Path("/tmp/wm_test.jpg")
    p.write_bytes(results[-1].read_bytes())
    apply_watermark(p)
    print("watermark_ok", p.stat().st_size)
else:
    print("watermark_skip_no_images")

token = os.environ["MAX_BOT_TOKEN"].strip().strip('"')
targets = lead_targets()
print("targets_count", len(targets))
kind, value = targets[0]
send_text(token, kind, value, "SOCO AI-примерка: тест канала заявок (можно игнорировать)")
print("max_text_ok", kind)
