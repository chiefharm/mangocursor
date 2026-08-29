"""Check if ClientID appears in Metrika CRM goals recently."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

CID = "1778157417318512003"
COUNTER = "64069270"
GOAL_CREATED = "345234413"
GOAL_PAID = "345234414"
ENV = Path(r"C:\Users\chief\Desktop\cursor\direct\.env")


def load_token() -> str:
    env: dict[str, str] = {}
    for raw in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env.get("YANDEX_DIRECT_TOKEN_PETROVEGO88") or env.get("METRIKA_TOKEN") or ""


def api(token: str, params: dict) -> dict:
    url = "https://api-metrika.yandex.net/stat/v1/data?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    token = load_token()
    date2 = date.today().isoformat()
    date1 = (date.today() - timedelta(days=2)).isoformat()
    print(f"looking for clientID={CID} dates={date1}..{date2}")

    for goal_id, label in ((GOAL_CREATED, "CRM created"), (GOAL_PAID, "CRM paid")):
        params = {
            "ids": COUNTER,
            "metrics": f"ym:s:goal{goal_id}reaches",
            "dimensions": "ym:s:clientID",
            "date1": date1,
            "date2": date2,
            "filters": f"ym:s:clientID=='{CID}'",
            "limit": 10,
            "accuracy": "full",
        }
        try:
            data = api(token, params)
        except Exception as exc:
            print(label, "ERR", exc)
            continue
        rows = data.get("data") or []
        totals = data.get("totals") or [0]
        print(f"{label}: rows={len(rows)} totals={totals}")
        for row in rows:
            print(" ", row)

    # Visits: try a few filter forms (Metrika is picky)
    for filt in (
        f"ym:s:clientID=='{CID}'",
        f"ym:s:clientID=={CID}",
        f"ym:s:clientID=@'{CID}'",
    ):
        params = {
            "ids": COUNTER,
            "metrics": "ym:s:visits,ym:s:users",
            "dimensions": "ym:s:clientID",
            "date1": date1,
            "date2": date2,
            "filters": filt,
            "limit": 10,
            "accuracy": "full",
        }
        try:
            data = api(token, params)
            print(f"visits filt={filt!r} rows={len(data.get('data') or [])} totals={data.get('totals')}")
            for row in data.get("data") or []:
                print(" ", row)
        except Exception as exc:
            print(f"visits filt={filt!r} ERR {exc}")


if __name__ == "__main__":
    main()
