#!/usr/bin/env python3
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


for host in ("https://soco-moscow.ru", "https://soco-kras.ru"):
    html = fetch(host + "/")
    hrefs = sorted(set(re.findall(r'href=["\'](/[^"\'#?]+)', html)))
    print("===", host, "paths", len(hrefs))
    for h in hrefs:
        hl = h.lower()
        if any(k in hl for k in ("port", "okras", "zav", "strizh", "men", "women", "curl", "color", "meb")):
            print(" ", h)

# probe candidates
cands = [
    "/portfoliomenmebversion",
    "/portfoliowomen",
    "/portfoliookrashivanie",
    "/portfoliookras",
    "/portfoliozavivka",
    "/zavivka",
    "/okrasivanie",
    "/okrashivanie",
    "/portfoliocolor",
]
for host in ("https://soco-moscow.ru", "https://soco-kras.ru"):
    for c in cands:
        url = host + c
        try:
            req = urllib.request.Request(url, headers=UA, method="HEAD")
            with urllib.request.urlopen(req, context=CTX, timeout=15) as r:
                print(r.status, url)
        except Exception as exc:
            code = getattr(getattr(exc, "code", None), "real", None) or getattr(exc, "code", None)
            print(code or type(exc).__name__, url)
