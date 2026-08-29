"""IP geolocation gate: Moscow (+ oblast) and Krasnoyarsk city only."""

from __future__ import annotations

import ipaddress
import os
import time

import httpx

# Default off — enable with TRYON_GEO_GATE=1 when ready.
GEO_GATE_ENABLED = os.getenv("TRYON_GEO_GATE", "0").strip().lower() in {"1", "true", "yes", "on"}

MSG_GEO_BLOCKED = (
    "Сервис доступен только для Москвы и Красноярска. "
    "Если вы уже здесь, попробуйте отключить VPN."
)

_ALLOWED_CITY = {
    "moscow",
    "moskva",
    "москва",
    "krasnoyarsk",
    "красноярск",
}
_ALLOWED_REGION = {
    # Moscow city / oblast — край Красноярска не входит
    "moscow",
    "moskva",
    "москва",
    "moscow oblast",
    "moskovskaya oblast",
    "московская область",
}
_KRASNOYARSK_CITY = {"krasnoyarsk", "красноярск"}
_KRASNOYARSK_KRAI = {
    "krasnoyarsk krai",
    "krasnoyarskiy kray",
    "krasnoyarsk territory",
    "красноярский край",
}

_CACHE_TTL_SEC = 24 * 3600
_cache: dict[str, tuple[float, bool, str]] = {}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("ё", "е").split())


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return True


def _is_krasnoyarsk_krai(region_n: str) -> bool:
    if not region_n:
        return False
    if region_n in _KRASNOYARSK_KRAI:
        return True
    return ("krai" in region_n or "kray" in region_n or "край" in region_n) and (
        "krasnoyarsk" in region_n or "краснояр" in region_n
    )


def _matches_allowed(city: str, region: str) -> bool:
    city_n = _norm(city)
    region_n = _norm(region)

    # Красноярский край: пускаем только если город именно Красноярск
    if _is_krasnoyarsk_krai(region_n):
        return city_n in _KRASNOYARSK_CITY

    if city_n in _ALLOWED_CITY:
        return True
    if region_n in _ALLOWED_REGION:
        return True
    return False


def check_client_geo(ip: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason_if_blocked).
    Private/loopback IPs are allowed (local/dev).
    On lookup failure — allow (fail-open).
    """
    if not GEO_GATE_ENABLED:
        return True, ""

    ip = (ip or "").strip()
    if not ip or _is_private(ip):
        return True, ""

    now = time.time()
    cached = _cache.get(ip)
    if cached and cached[0] > now:
        return cached[1], ("" if cached[1] else MSG_GEO_BLOCKED)

    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,message,countryCode,regionName,city", "lang": "en"},
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(data.get("message") or "geo lookup failed")

        country = (data.get("countryCode") or "").upper()
        city = data.get("city") or ""
        region = data.get("regionName") or ""
        label = f"{country}:{city}/{region}"
        allowed = country == "RU" and _matches_allowed(city, region)
    except Exception as exc:  # noqa: BLE001
        print(f"geo_gate_lookup_failed ip={ip} err={exc}")
        return True, ""

    _cache[ip] = (now + _CACHE_TTL_SEC, allowed, label)
    if len(_cache) > 5000:
        expired = [k for k, v in _cache.items() if v[0] <= now]
        for k in expired[:1000]:
            _cache.pop(k, None)

    return allowed, ("" if allowed else MSG_GEO_BLOCKED)
