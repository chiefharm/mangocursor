#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static" / "portfolio"
MANIFEST = ROOT / "manifest.json"
WORK = Path(__file__).resolve().parents[1] / "_portfolio_work" / "portfolio_prune2"
REMOVE = set()  # set explicitly before each run, e.g. {"women_35"}


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    new_cats = []
    for cat in data["categories"]:
        kept = [it for it in cat["items"] if it["id"] not in REMOVE]
        dropped = [it["id"] for it in cat["items"] if it["id"] in REMOVE]
        print(cat["id"], "dropped", dropped, "kept", len(kept))
        cat_dir = WORK / cat["id"]
        cat_dir.mkdir()
        items = []
        for i, it in enumerate(kept, 1):
            src_full = ROOT / cat["id"] / Path(it["src"]).name
            src_thumb = ROOT / cat["id"] / Path(it["thumb"]).name
            new_id = f"{cat['id']}_{i:02d}"
            shutil.copy2(src_full, cat_dir / f"{new_id}.jpg")
            shutil.copy2(
                src_thumb if src_thumb.exists() else src_full,
                cat_dir / f"{new_id}_t.jpg",
            )
            items.append(
                {
                    "id": new_id,
                    "src": f"/static/portfolio/{cat['id']}/{new_id}.jpg",
                    "thumb": f"/static/portfolio/{cat['id']}/{new_id}_t.jpg",
                    "source_url": it.get("source_url", ""),
                    "file_hash": it.get("file_hash", ""),
                }
            )
        new_cats.append({"id": cat["id"], "title": cat["title"], "items": items})
    for child in list(ROOT.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for cat in new_cats:
        shutil.copytree(WORK / cat["id"], ROOT / cat["id"])
    MANIFEST.write_text(
        json.dumps({"categories": new_cats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print([(c["id"], len(c["items"])) for c in new_cats])


if __name__ == "__main__":
    main()
