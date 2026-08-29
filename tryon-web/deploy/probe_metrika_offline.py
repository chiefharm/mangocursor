"""Probe Yandex Metrika offline conversions using token from cursor/direct .env."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
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


def api_get(token: str, url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"OAuth {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return {"_error": exc.code, "_body": body[:2000]}


def main() -> None:
    env = load_env(DIRECT_ENV)
    token = (
        env.get("YANDEX_DIRECT_TOKEN_PETROVEGO88")
        or env.get("METRIKA_TOKEN")
        or env.get("YANDEX_METRIKA_TOKEN")
        or ""
    )
    src = (
        "PETROVEGO88"
        if env.get("YANDEX_DIRECT_TOKEN_PETROVEGO88")
        else ("METRIKA_TOKEN" if env.get("METRIKA_TOKEN") else "OTHER")
    )
    print(f"token_source={src} token_len={len(token)}")
    if not token:
        print("NO TOKEN")
        return

    # Counters visible to token
    me = api_get(token, "https://api-metrika.yandex.net/management/v1/counters")
    if "_error" in me:
        print("counters error", me)
    else:
        rows = me.get("counters") or []
        print(f"counters_visible={len(rows)}")
        for c in rows[:20]:
            print(f"  id={c.get('id')} name={c.get('name')} site={c.get('site')}")

    for counter in COUNTERS:
        print(f"\n=== counter {counter} ===")
        # Offline conversion uploadings
        for path in (
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/offline_conversions/uploadings",
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/offline_conversions/uploading",
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/offline_conversions",
        ):
            data = api_get(token, path)
            print(f"GET {path.split(str(counter))[-1]}")
            if "_error" in data:
                print(f"  err={data['_error']} body={data['_body'][:300]}")
            else:
                print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
                break

        # Goals (look for CRM / offline related)
        goals = api_get(
            token,
            f"https://api-metrika.yandex.net/management/v1/counter/{counter}/goals",
        )
        if "_error" in goals:
            print("goals err", goals["_error"], goals["_body"][:200])
        else:
            print("goals:")
            for g in goals.get("goals") or []:
                name = str(g.get("name") or "")
                low = name.lower()
                if any(
                    x in low
                    for x in (
                        "заказ",
                        "crm",
                        "офлайн",
                        "offline",
                        "сделк",
                        "покуп",
                        "конверс",
                    )
                ):
                    print(
                        f"  id={g.get('id')} type={g.get('type')} name={name!r} "
                        f"conditions={g.get('conditions')}"
                    )


if __name__ == "__main__":
    main()
