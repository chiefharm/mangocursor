#!/usr/bin/env python3
"""Check embed_tryon_link.js on main sites and simulate URL merge."""
import re
import ssl
import urllib.parse
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SITES = [
    ("soco-salon.ru", "https://soco-salon.ru/"),
    ("soco-moscow.ru", "https://soco-moscow.ru/"),
    ("soco-kras.ru", "https://soco-kras.ru/"),
]

HOST_COUNTERS = {
    "soco-salon.ru": 64069270,
    "www.soco-salon.ru": 64069270,
    "soco-moscow.ru": 95469576,
    "www.soco-moscow.ru": 95469576,
    "soco-kras.ru": 64069270,
    "www.soco-kras.ru": 64069270,
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, context=CTX, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def simulate_build_url(source_href: str, client_id: str = "TEST_CLIENT_123") -> str:
    u = urllib.parse.urlparse(source_href)
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    q["ym_cid"] = [client_id[:64]]
    if not q.get("return_url") and not q.get("from"):
        q["from"] = ["https://soco-salon.ru/"]
    new_query = urllib.parse.urlencode({k: v[0] for k, v in q.items()})
    return urllib.parse.urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))


def main() -> None:
    print("=== embed_tryon_link.js on VPS ===")
    js_url = "https://primerka.soco-salon.ru/static/embed_tryon_link.js"
    js = fetch(js_url)
    print(f"OK {js_url} ({len(js)} bytes)")
    for needle in ("sourceHref", "return_url", "HOST_COUNTERS"):
        print(f"  contains {needle!r}: {needle in js}")

    print("\n=== Main sites ===")
    for host, url in SITES:
        html = fetch(url)
        embed = "embed_tryon_link.js" in html
        primerka_links = re.findall(r'href="(https://primerka\.soco-salon\.ru[^"]*)"', html)
        ym = re.search(r"ym\((\d+),\s*['\"]init", html)
        expected = HOST_COUNTERS.get(host, 0)
        print(f"\n{host}:")
        print(f"  embed script in footer: {'YES' if embed else 'NO'}")
        print(f"  metrika on page: {ym.group(1) if ym else '?'} (expected {expected})")
        print(f"  primerka links on homepage: {len(primerka_links)}")
        for link in primerka_links[:3]:
            print(f"    href: {link}")
            print(f"    after click (sim): {simulate_build_url(link)}")

    print("\n=== primerka health ===")
    req = urllib.request.Request("https://primerka.soco-salon.ru/", headers=UA, method="GET")
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        print(f"  GET / -> HTTP {r.status}")
        body = r.read(500).decode("utf-8", "replace")
        print(f"  has app.js: {'/static/app.js' in body or 'app.js' in body}")


if __name__ == "__main__":
    main()
