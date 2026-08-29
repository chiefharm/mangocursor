#!/usr/bin/env python3
from __future__ import annotations

import re
import ssl
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0"}
PAGES = [
    "https://soco-salon.ru/",
    "https://soco-kras.ru/",
    "https://soco-moscow.ru/",
    "https://soco-salon.ru/taplink",
    "https://soco-kras.ru/taplink2gisloyality",
    "https://soco-moscow.ru/taplink",
    "https://primerka.soco-salon.ru/",
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def main() -> None:
    for url in PAGES:
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"\n==== {url} ERR {exc}")
            continue
        print(f"\n==== {url} len={len(html)}")
        print(" embed_tryon:", "embed_tryon_link.js" in html)
        print(" has Marquiz:", "Marquiz" in html or "marquiz" in html.lower())
        print(" form ym_cid:", "ym_cid" in html and "getClientID" in html)

        for m in re.finditer(
            r".{0,100}(подобрать мастера|знаю мастера|запишусь самостоятельно).{0,160}",
            html,
            flags=re.I | re.S,
        ):
            s = re.sub(r"\s+", " ", m.group(0))[:240]
            print(" HIT:", s)

        for m in re.finditer(r'href="([^"]*(?:mrqz\.me|marquiz|taplink)[^"]*)"', html, flags=re.I):
            print(" href:", m.group(1)[:200])

        # Marquiz button / onclick patterns
        for m in re.finditer(r"Marquiz\.(open|show|add)\([^)]{0,120}\)", html):
            print(" mq:", m.group(0)[:160])

        idx = html.find("getClientID")
        if idx >= 0:
            print(" getClientID context:", re.sub(r"\s+", " ", html[idx - 80 : idx + 200])[:260])


if __name__ == "__main__":
    main()
