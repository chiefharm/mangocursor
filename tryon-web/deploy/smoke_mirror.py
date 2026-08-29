#!/usr/bin/env python3
from pathlib import Path
from app.watermark import mirror_selfie

src = next(Path("/opt/soco-tryon/data/uploads").glob("*/before*"))
dst = Path("/tmp/mirror_check.jpg")
dst.write_bytes(src.read_bytes())
before = dst.stat().st_size
mirror_selfie(dst)
print("src", src)
print("before_bytes", before, "after_bytes", dst.stat().st_size)
