#!/usr/bin/env python3
"""Rebuild portfolio from Desktop/cursor/примерка (5 subfolders = 5 tabs)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

THUMB_SIDE = 420
FULL_SIDE = 900
JPEG_Q_THUMB = 70
JPEG_Q_FULL = 82
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tif", ".tiff", ".jfif"}

# Tab order in UI (folder title substring → slug id)
CATEGORY_ORDER = [
    ("женск", "длин", "zhen_dlinnye"),
    ("женск", "корот", "zhen_korotkie"),
    ("женск", "средн", "zhen_srednie"),
    ("женск", "кудр", "zhen_kudri"),
    ("мужск", None, "muzhskie"),
]


def content_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


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


def wipe_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def slug_for_folder(name: str) -> str:
    low = name.lower()
    for a, b, slug in CATEGORY_ORDER:
        if a in low and (b is None or b in low):
            return slug
    safe = re.sub(r"[^a-z0-9]+", "_", name.lower())
    safe = safe.strip("_") or "cat"
    return safe[:32]


def folder_sort_key(path: Path) -> tuple[int, str]:
    low = path.name.lower()
    for i, (a, b, _) in enumerate(CATEGORY_ORDER):
        if a in low and (b is None or b in low):
            return (i, path.name)
    return (99, path.name)


def build_category(cat_id: str, title: str, sources: list[Path], out_dir: Path, used_md5: set[str]) -> list[dict]:
    wipe_dir(out_dir)
    items: list[dict] = []
    for path in sources:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            print("READ_FAIL", path, exc)
            continue
        md = content_md5(raw)
        if md in used_md5:
            print("SKIP_DUP", cat_id, path.name)
            continue
        try:
            full = to_jpeg(raw, FULL_SIDE, JPEG_Q_FULL)
            thumb = to_jpeg(raw, THUMB_SIDE, JPEG_Q_THUMB)
        except Exception as exc:  # noqa: BLE001
            print("JPEG_FAIL", path, exc)
            continue
        used_md5.add(md)
        idx = len(items) + 1
        name = f"{cat_id}_{idx:02d}.jpg"
        thumb_name = f"{cat_id}_{idx:02d}_t.jpg"
        (out_dir / name).write_bytes(full)
        (out_dir / thumb_name).write_bytes(thumb)
        item = {
            "id": f"{cat_id}_{idx:02d}",
            "src": f"/static/portfolio/{cat_id}/{name}",
            "thumb": f"/static/portfolio/{cat_id}/{thumb_name}",
            "source_url": path.name,
            "file_hash": md,
        }
        items.append(item)
        print("OK", item["id"], f"{len(thumb) // 1024}KB", path.name[:50])
    return items


def main() -> int:
    cursor_root = Path(__file__).resolve().parents[2].parent  # Desktop/cursor
    src_root = cursor_root / "примерка"
    out = Path(__file__).resolve().parents[1] / "static" / "portfolio"

    if not src_root.is_dir():
        print("Missing source folder:", src_root)
        return 1

    folders = sorted(
        [p for p in src_root.iterdir() if p.is_dir()],
        key=folder_sort_key,
    )
    if not folders:
        print("No subfolders in", src_root)
        return 1

    print("SOURCE", src_root)
    for f in folders:
        n = sum(1 for p in f.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        print(" ", f.name, "->", slug_for_folder(f.name), f"({n} images)")

    wipe_dir(out)
    used: set[str] = set()
    categories = []
    for folder in folders:
        cat_id = slug_for_folder(folder.name)
        sources = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )
        items = build_category(cat_id, folder.name, sources, out / cat_id, used)
        categories.append({"id": cat_id, "title": folder.name, "items": items})
        print("FINAL", cat_id, len(items))

    manifest = {"categories": categories}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out / "manifest.json")
    print("TOTAL", sum(len(c["items"]) for c in categories), "images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
