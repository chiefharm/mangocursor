#!/usr/bin/env python3
"""Rebuild portfolio into only men / women from local folders + existing site photos."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

THUMB_SIDE = 420
FULL_SIDE = 900
JPEG_Q_THUMB = 70
JPEG_Q_FULL = 82

# Existing curl/color items reclassified by visual review (2026-08-03)
CURL_TO_MEN = {"curl_01", "curl_02", "curl_03", "curl_04", "curl_05"}
CURL_TO_WOMEN = {"curl_06", "curl_07", "curl_08"}
# All color_* → women

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tif", ".tiff"}


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


def collect_sources(
    existing: Path,
    men_src: Path,
    women_src: Path,
) -> dict[str, list[tuple[Path, str]]]:
    """Return {men|women: [(path, label), ...]}."""
    buckets: dict[str, list[tuple[Path, str]]] = {"men": [], "women": []}

    # Existing site categories
    for p in sorted((existing / "men").glob("*.jpg")):
        if p.name.endswith("_t.jpg"):
            continue
        buckets["men"].append((p, f"site:{p.name}"))

    for p in sorted((existing / "women").glob("*.jpg")):
        if p.name.endswith("_t.jpg"):
            continue
        buckets["women"].append((p, f"site:{p.name}"))

    for p in sorted((existing / "curl").glob("*.jpg")):
        if p.name.endswith("_t.jpg"):
            continue
        stem = p.stem  # curl_01
        if stem in CURL_TO_MEN:
            buckets["men"].append((p, f"site:{p.name}"))
        elif stem in CURL_TO_WOMEN:
            buckets["women"].append((p, f"site:{p.name}"))
        else:
            print("WARN unknown curl", stem, "→ women")
            buckets["women"].append((p, f"site:{p.name}"))

    for p in sorted((existing / "color").glob("*.jpg")):
        if p.name.endswith("_t.jpg"):
            continue
        buckets["women"].append((p, f"site:{p.name}"))

    # User-provided folders
    for p in sorted(men_src.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            buckets["men"].append((p, f"user:{p.name}"))

    for p in sorted(women_src.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            buckets["women"].append((p, f"user:{p.name}"))

    return buckets


def build_category(
    cat: str,
    sources: list[tuple[Path, str]],
    out_dir: Path,
    used_md5: set[str],
) -> list[dict]:
    wipe_dir(out_dir)
    items: list[dict] = []
    for path, label in sources:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            print("READ_FAIL", path, exc)
            continue
        md = content_md5(raw)
        if md in used_md5:
            print("SKIP_DUP", cat, label)
            continue
        try:
            full = to_jpeg(raw, FULL_SIDE, JPEG_Q_FULL)
            thumb = to_jpeg(raw, THUMB_SIDE, JPEG_Q_THUMB)
        except Exception as exc:  # noqa: BLE001
            print("JPEG_FAIL", path, exc)
            continue
        used_md5.add(md)
        idx = len(items) + 1
        name = f"{cat}_{idx:02d}.jpg"
        thumb_name = f"{cat}_{idx:02d}_t.jpg"
        (out_dir / name).write_bytes(full)
        (out_dir / thumb_name).write_bytes(thumb)
        item = {
            "id": f"{cat}_{idx:02d}",
            "src": f"/static/portfolio/{cat}/{name}",
            "thumb": f"/static/portfolio/{cat}/{thumb_name}",
            "source_url": label,
            "file_hash": md,
        }
        items.append(item)
        print(
            "OK",
            item["id"],
            f"{len(thumb)//1024}KB",
            label[:60],
        )
    return items


def main() -> int:
    root = Path(__file__).resolve().parents[2]  # mangocursor
    cursor_root = root.parent  # Desktop/cursor
    existing = Path(__file__).resolve().parents[1] / "_portfolio_work" / "portfolio"
    men_src = cursor_root / "мужские для примерки"
    women_src = cursor_root / "женские для примерки"
    out = Path(__file__).resolve().parents[1] / "static" / "portfolio"

    if not existing.is_dir():
        print("Missing existing portfolio at", existing)
        return 1
    if not men_src.is_dir() or not women_src.is_dir():
        print("Missing user folders:", men_src, women_src)
        return 1

    buckets = collect_sources(existing, men_src, women_src)
    print("SOURCES men", len(buckets["men"]), "women", len(buckets["women"]))

    wipe_dir(out)
    used: set[str] = set()
    manifest = {
        "categories": [
            {
                "id": "men",
                "title": "Мужские",
                "items": build_category("men", buckets["men"], out / "men", used),
            },
            {
                "id": "women",
                "title": "Женские",
                "items": build_category("women", buckets["women"], out / "women", used),
            },
        ]
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for cat in manifest["categories"]:
        print("FINAL", cat["id"], len(cat["items"]))
    print("WROTE", out / "manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
