#!/usr/bin/env python3
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0"}
cands = [
    "/portfoliocolor",
    "/portfoliocurls",
    "/portfoliocurl",
    "/portfoliohimozavivka",
    "/portfoliozaviv",
    "/himozavivka",
    "/biovavivka",
    "/biovavivka",
    "/biokhimozavivka",
    "/portfoliohim",
    "/portfoliowave",
    "/zavivkavolos",
    "/portfolio-zavivka",
]
for host in ("https://soco-moscow.ru", "https://soco-kras.ru"):
    for c in cands:
        url = host + c
        try:
            req = urllib.request.Request(url, headers=UA, method="HEAD")
            with urllib.request.urlopen(req, context=CTX, timeout=12) as r:
                print(r.status, url)
        except Exception as exc:
            print(getattr(exc, "code", type(exc).__name__), url)
