#!/usr/bin/env python3
"""Remove selected portfolio ids and renumber remaining items."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static" / "portfolio"
MANIFEST = ROOT / "manifest.json"
WORK = Path(__file__).resolve().parents[1] / "_portfolio_work" / "portfolio_prune"
BACKUP = Path(__file__).resolve().parents[1] / "_portfolio_work" / "portfolio_before_prune"

RAW = """
men_09, men_12, men_13, men_17, men_18, men_21, men_24, men_25, men_27, men_28, men_29, men_30, men_32, men_33, men_35, men_36,
women_09, women_10, women_11, women_13, women_17, women_18, women_19, women_20, women_21, women_22, women_23, women_24, women_25, women_26, women_27, women_28, women_29, women_30, women_31, women_32, women_36, women_37, women_38, women_34, women_52, women_53, women_54, women_59, women_65
"""


def main() -> None:
    remove = set(re.findall(r"(?:men|women)_\d+", RAW))
    print("remove", len(remove), sorted(remove))

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    existing_ids = {it["id"] for cat in data["categories"] for it in cat["items"]}
    missing = sorted(remove - existing_ids)
    if missing:
        print("WARN not in manifest:", missing)

    new_cats = []
    for cat in data["categories"]:
        kept = [it for it in cat["items"] if it["id"] not in remove]
        dropped = [it["id"] for it in cat["items"] if it["id"] in remove]
        print(cat["id"], "kept", len(kept), "dropped", len(dropped))

        cat_dir = WORK / cat["id"]
        cat_dir.mkdir(parents=True)
        new_items = []
        for i, it in enumerate(kept, 1):
            src_full = ROOT / cat["id"] / Path(it["src"]).name
            src_thumb = ROOT / cat["id"] / Path(it["thumb"]).name
            if not src_full.exists():
                print("MISSING", src_full)
                continue
            new_id = f"{cat['id']}_{i:02d}"
            full_name = f"{new_id}.jpg"
            thumb_name = f"{new_id}_t.jpg"
            shutil.copy2(src_full, cat_dir / full_name)
            if src_thumb.exists():
                shutil.copy2(src_thumb, cat_dir / thumb_name)
            else:
                shutil.copy2(src_full, cat_dir / thumb_name)
            new_items.append(
                {
                    "id": new_id,
                    "src": f"/static/portfolio/{cat['id']}/{full_name}",
                    "thumb": f"/static/portfolio/{cat['id']}/{thumb_name}",
                    "source_url": it.get("source_url", ""),
                    "file_hash": it.get("file_hash", ""),
                }
            )
        new_cats.append({"id": cat["id"], "title": cat["title"], "items": new_items})

    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    shutil.copytree(ROOT, BACKUP)

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
    for c in new_cats:
        print("FINAL", c["id"], len(c["items"]))


if __name__ == "__main__":
    main()
