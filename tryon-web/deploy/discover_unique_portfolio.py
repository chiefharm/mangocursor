#!/usr/bin/env python3
"""Discover unique Vigbo images from SOCO pages; dump candidates for curl curation."""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0"}
OUT = Path("/tmp/soco_portfolio_discover")
OUT.mkdir(parents=True, exist_ok=True)

PAGES = {
    "men": [
        "https://soco-moscow.ru/portfoliomenmebversion",
        "https://soco-kras.ru/portfoliomenmebversion",
    ],
    "women": [
        "https://soco-moscow.ru/portfoliowomen",
        "https://soco-kras.ru/portfoliowomen",
    ],
    "color": ["https://soco-moscow.ru/portfoliocolor"],
    "misc": [
        "https://soco-moscow.ru/uslugi",
        "https://soco-moscow.ru/",
        "https://soco-kras.ru/uslugi",
        "https://soco-kras.ru/",
    ],
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=40) as r:
        return r.read().decode("utf-8", errors="replace")


def extract(html: str) -> list[str]:
    found = []
    pats = [
        r"(https?://cdn-st3\.vigbo\.com[^\"'\\s<>]+\.(?:jpe?g|png|webp))",
        r"(//cdn-st3\.vigbo\.com[^\"'\\s<>]+\.(?:jpe?g|png|webp))",
    ]
    for pat in pats:
        for m in re.findall(pat, html, flags=re.I):
            u = m
            if u.startswith("//"):
                u = "https:" + u
            low = u.lower()
            if any(x in low for x in ("logo", "favicon", "icon", "sprite", "1x1")):
                continue
            if u not in found:
                found.append(u)
    return found


def bn_key(url: str) -> str:
    name = url.split("?")[0].split("/")[-1].lower()
    m = re.search(r"([a-f0-9]{16,})", name)
    return m.group(1) if m else name


def main() -> None:
    catalog = {}
    global_bn = set()
    global_md5 = set()
    for cat, pages in PAGES.items():
        cat_dir = OUT / cat
        cat_dir.mkdir(exist_ok=True)
        items = []
        for page in pages:
            try:
                html = fetch(page)
            except Exception as exc:
                print("FAIL", page, exc)
                continue
            print("PAGE", page, len(html))
            for u in extract(html):
                bk = bn_key(u)
                if bk in global_bn:
                    continue
                try:
                    req = urllib.request.Request(u, headers=UA)
                    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
                        data = r.read()
                except Exception as exc:
                    print("DL", exc)
                    continue
                if len(data) < 4000:
                    continue
                h = hashlib.md5(data).hexdigest()
                if h in global_md5:
                    print("DUP_BYTES", bk)
                    continue
                global_bn.add(bk)
                global_md5.add(h)
                ext = ".jpg"
                low = u.lower()
                if ".png" in low:
                    ext = ".png"
                elif ".webp" in low:
                    ext = ".webp"
                name = f"{cat}_{len(items)+1:02d}_{h[:8]}{ext}"
                (cat_dir / name).write_bytes(data)
                items.append({"file": name, "url": u, "md5": h, "kb": len(data) // 1024})
                print("OK", cat, name, len(data) // 1024, "KB")
        catalog[cat] = items
        print("CAT", cat, len(items))
    (OUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    # links mentioning portfolio
    try:
        home = fetch("https://soco-moscow.ru/")
        for L in sorted(set(re.findall(r'href=["\']([^"\']+)["\']', home))):
            if any(x in L.lower() for x in ("portfol", "zaviv", "curl", "him", "био", "кудр")):
                print("LINK", L)
    except Exception as exc:
        print("home fail", exc)
    print("DONE", OUT)


if __name__ == "__main__":
    main()
