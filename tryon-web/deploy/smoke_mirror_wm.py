#!/usr/bin/env python3
from pathlib import Path
from app.watermark import apply_watermark, mirror_selfie

uploads = sorted(Path("/opt/soco-tryon/data/uploads").glob("*/before*"))
src = uploads[-1]
dst = Path("/tmp/mirror_wm_test.jpg")
dst.write_bytes(src.read_bytes())
out = mirror_selfie(dst)
print("mirrored", out, out.stat().st_size)
apply_watermark(out)
print("watermarked", out.stat().st_size)
