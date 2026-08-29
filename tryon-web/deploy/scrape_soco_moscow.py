#!/usr/bin/env python3
"""Extract image URLs from soco-moscow.ru portfolio pages."""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

PAGES = [
    "https://soco-moscow.ru/",
    "https://soco-moscow.ru/uslugi",
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")


def extract_imgs(html: str) -> list[str]:
    urls: list[str] = []
    # src, data-src, data-original, background images
    for pat in (
        r'(?:src|data-src|data-original|data-lazy|data-bg)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
        r'url\(([^)]+\.(?:jpg|jpeg|png|webp)[^)]*)\)',
        r'(https?://cdn[^"\'\s>]+\.(?:jpg|jpeg|png|webp)[^"\'\s>]*)',
        r'(//cdn[^"\'\s>]+\.(?:jpg|jpeg|png|webp)[^"\'\s>]*)',
        r'(https?://[^"\'\s>]*vigbo[^"\'\s>]+\.(?:jpg|jpeg|png|webp)[^"\'\s>]*)',
    ):
        for m in re.findall(pat, html, flags=re.I):
            u = m.strip().strip('"').strip("'")
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("/"):
                u = "https://soco-moscow.ru" + u
            if any(x in u.lower() for x in ("favicon", "logo", "icon", "sprite", "pixel", "1x1")):
                continue
            if u not in urls:
                urls.append(u)
    return urls


def main() -> None:
    all_urls: list[str] = []
    for page in PAGES:
        try:
            html = fetch(page)
            Path(f"/tmp/soco_{page.rstrip('/').split('/')[-1] or 'home'}.html").write_text(html, encoding="utf-8")
            found = extract_imgs(html)
            print(page, "bytes", len(html), "imgs", len(found))
            for u in found[:15]:
                print(" ", u[:160])
            for u in found:
                if u not in all_urls:
                    all_urls.append(u)
        except Exception as exc:
            print("FAIL", page, exc)
    Path("/tmp/soco_portfolio_urls.json").write_text(
        json.dumps(all_urls, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("TOTAL", len(all_urls))


if __name__ == "__main__":
    main()
