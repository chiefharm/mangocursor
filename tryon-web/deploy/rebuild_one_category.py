#!/usr/bin/env python3
"""Rebuild a single portfolio category from примерка subfolder."""
from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

THUMB_SIDE = 420
FULL_SIDE = 900
JPEG_Q_THUMB = 70
JPEG_Q_FULL = 82
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tif", ".tiff", ".jfif"}


def to_jpeg(data: bytes, max_side: int, quality: int) -> bytes:
    img = Image.open(BytesIO(data))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / m
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def find_folder(src_root: Path, cat_id: str) -> Path | None:
    for p in src_root.iterdir():
        if not p.is_dir():
            continue
        low = p.name.lower()
        if cat_id == "zhen_dlinnye" and "длин" in low and "женск" in low:
            return p
    return None


def main() -> int:
    cat_id = sys.argv[1] if len(sys.argv) > 1 else "zhen_dlinnye"
    src_root = Path(__file__).resolve().parents[2].parent / "примерка"
    portfolio = Path(__file__).resolve().parents[1] / "static" / "portfolio"
    manifest_path = portfolio / "manifest.json"

    folder = find_folder(src_root, cat_id)
    if not folder:
        print("Folder not found for", cat_id, "in", src_root)
        return 1

    sources = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    print("SOURCE", folder, "files", len(sources))

    out_dir = portfolio / cat_id
    if out_dir.exists():
        for f in out_dir.iterdir():
            f.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    seen_in_folder: set[str] = set()
    for path in sources:
        raw = path.read_bytes()
        md = hashlib.md5(raw).hexdigest()
        if md in seen_in_folder:
            print("SKIP_SAME_BYTES", path.name)
            continue
        seen_in_folder.add(md)
        try:
            full = to_jpeg(raw, FULL_SIDE, JPEG_Q_FULL)
            thumb = to_jpeg(raw, THUMB_SIDE, JPEG_Q_THUMB)
        except Exception as exc:  # noqa: BLE001
            print("JPEG_FAIL", path.name, exc)
            continue
        idx = len(items) + 1
        name = f"{cat_id}_{idx:02d}.jpg"
        thumb_name = f"{cat_id}_{idx:02d}_t.jpg"
        (out_dir / name).write_bytes(full)
        (out_dir / thumb_name).write_bytes(thumb)
        items.append(
            {
                "id": f"{cat_id}_{idx:02d}",
                "src": f"/static/portfolio/{cat_id}/{name}",
                "thumb": f"/static/portfolio/{cat_id}/{thumb_name}",
                "source_url": path.name,
                "file_hash": md,
            }
        )
        print("OK", f"{cat_id}_{idx:02d}", path.name)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    title = folder.name
    updated = False
    for cat in manifest["categories"]:
        if cat["id"] == cat_id:
            cat["title"] = title
            cat["items"] = items
            updated = True
            break
    if not updated:
        manifest["categories"].insert(0, {"id": cat_id, "title": title, "items": items})

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", len(items), "items to", cat_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
