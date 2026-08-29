"""Probe Metrika CDP/orders (CRM goals) — how 1C likely sends deals."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

DIRECT_ENV = Path(r"C:\Users\chief\Desktop\cursor\direct\.env")
COUNTERS = ("64069270", "95469576")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def api_get(token: str, url: str) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"OAuth {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return {"_error": exc.code, "_body": body[:2500], "_url": url}


def show(label: str, data) -> None:
    print(f"\n-- {label} --")
    if isinstance(data, dict) and "_error" in data:
        print(f"ERR {data['_error']}: {data['_body'][:500]}")
        return
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text[:5000])
    if len(text) > 5000:
        print(f"... truncated, total_chars={len(text)}")


def main() -> None:
    env = load_env(DIRECT_ENV)
    token = env.get("YANDEX_DIRECT_TOKEN_PETROVEGO88") or env.get("METRIKA_TOKEN") or ""
    print(f"token_len={len(token)}")

    for counter in COUNTERS:
        print(f"\n########## COUNTER {counter} ##########")
        endpoints = [
            f"https://api-metrika.yandex.net/cdp/api/v1/counter/{counter}/schema/orders",
            f"https://api-metrika.yandex.net/cdp/api/v1/counter/{counter}/schema/contacts",
            f"https://api-metrika.yandex.net/cdp/api/v1/counter/{counter}/data/orders?limit=5",
            f"https://api-metrika.yandex.net/cdp/api/v1/counter/{counter}/data/orders?limit=5&offset=0",
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/offline_conversions/extended_threshold",
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/offline_conversions/visit_join_threshold",
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/grants",
        ]
        for url in endpoints:
            show(url.split(f"/{counter}/")[-1], api_get(token, url))

        # Recent CRM goal hits via Stats API — sample clientIDs if available
        from datetime import date, timedelta
        import urllib.parse

        date2 = date.today().isoformat()
        date1 = (date.today() - timedelta(days=7)).isoformat()
        params = {
            "ids": counter,
            "metrics": "ym:s:goal345234413reaches" if counter == "64069270" else "ym:s:goal336854689reaches",
            "dimensions": "ym:s:clientID",
            "date1": date1,
            "date2": date2,
            "limit": 10,
            "accuracy": "full",
        }
        # CRM goal ids differ per counter — set properly
        if counter == "64069270":
            params["metrics"] = "ym:s:goal345234413reaches"
        else:
            params["metrics"] = "ym:s:goal336854689reaches"
        url = "https://api-metrika.yandex.net/stat/v1/data?" + urllib.parse.urlencode(params)
        show(f"stat clientID for CRM created ({date1}..{date2})", api_get(token, url))


if __name__ == "__main__":
    main()
