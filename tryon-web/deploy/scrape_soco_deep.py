#!/usr/bin/env python3
"""Deep-scrape Vigbo SOCO sites for portfolio photos."""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")


def imgs(html: str, base: str) -> list[str]:
    found: list[str] = []
    pats = [
        r'(?:src|data-src|data-original|data-lazy|href)=["\']([^"\']+\.(?:jpe?g|png|webp)(?:\?[^"\']*)?)["\']',
        r'(https?://cdn[^"\'\s<>]+\.(?:jpe?g|png|webp)(?:\?[^"\'\s<>]*)?)',
        r'(//cdn[^"\'\s<>]+\.(?:jpe?g|png|webp)(?:\?[^"\'\s<>]*)?)',
    ]
    for pat in pats:
        for m in re.findall(pat, html, flags=re.I):
            u = m.strip()
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                u = urljoin(base, u)
            low = u.lower()
            if any(x in low for x in ("favicon", "logo", "icon", "sprite", "pixel", "1x1", ".svg")):
                continue
            if u not in found:
                found.append(u)
    return found


def links(html: str, base: str) -> list[str]:
    out = []
    for m in re.findall(r'href=["\']([^"\']+)["\']', html):
        if m.startswith("#") or m.startswith("mailto:") or m.startswith("tel:"):
            continue
        u = urljoin(base, m)
        if "soco-moscow.ru" in u or "soco-kras.ru" in u:
            out.append(u.split("?")[0].rstrip("/"))
    return sorted(set(out))


SEEDS = [
    "https://soco-moscow.ru",
    "https://soco-moscow.ru/uslugi",
    "https://soco-kras.ru",
]


def main() -> None:
    seen_pages: set[str] = set()
    queue = list(SEEDS)
    all_imgs: list[str] = []
    while queue and len(seen_pages) < 40:
        url = queue.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            html = fetch(url if url.endswith("/") or "." in url.rsplit("/", 1)[-1] else url + "/")
        except Exception:
            try:
                html = fetch(url)
            except Exception as exc:
                print("FAIL", url, exc)
                continue
        print("OK", url, len(html))
        for u in imgs(html, url):
            if u not in all_imgs:
                all_imgs.append(u)
        if "soco-moscow.ru" in url or "soco-kras.ru" in url:
            for L in links(html, url):
                if L not in seen_pages and L not in queue:
                    # skip heavy pages
                    if any(x in L for x in ("/blog", "/news", "taplink", "politika", "cookie")):
                        continue
                    queue.append(L)

    Path("/tmp/soco_all_imgs.json").write_text(json.dumps(all_imgs, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PAGES", len(seen_pages), "IMGS", len(all_imgs))
    for u in all_imgs[:40]:
        print(u)


if __name__ == "__main__":
    main()
