"""Multi-site Mango + Telegram routing (Moscow, Krasnoyarsk, …)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class SiteConfig:
    site_id: str
    label: str
    account: str
    api_key: str
    api_salt: str
    line_number: str
    group_chat_ids: List[str]
    tz_name: str = "Europe/Moscow"

    def calls_dir(self, base_dir: Path) -> Path:
        site_dir = base_dir / "calls" / self.site_id
        if self.site_id == "moscow" and not site_dir.exists():
            if any(base_dir.glob("20*__*.html")):
                return base_dir
        site_dir.mkdir(parents=True, exist_ok=True)
        return site_dir

    def docx_dir(self, base_dir: Path) -> Path:
        return base_dir / "telegram_docx" / self.site_id

    def state_file(self, base_dir: Path) -> Path:
        return base_dir / "data" / f"sent_calls_{self.site_id}.json"

    def calls_index(self, base_dir: Path) -> Path:
        return base_dir / "data" / f"calls_index_{self.site_id}.json"

    def yandex_cache_dir(self, base_dir: Path) -> Path:
        return base_dir / "data" / "yandex_cache" / self.site_id

    def webhooks_dir(self, base_dir: Path) -> Path:
        return base_dir / "data" / "webhooks" / self.site_id


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _chat_id_list(raw: str) -> List[str]:
    ids: List[str] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part and part not in ids:
            ids.append(part)
    return ids


def _site_from_env(site_id: str) -> SiteConfig | None:
    prefix = f"SITE_{site_id.upper()}_"
    label = _env(f"{prefix}LABEL")
    account = _env(f"{prefix}ACCOUNT")
    api_key = _env(f"{prefix}API_KEY")
    api_salt = _env(f"{prefix}API_SALT")
    line_number = _env(f"{prefix}LINE_NUMBER")
    group_ids = _chat_id_list(_env(f"{prefix}GROUP_CHAT_IDS"))
    tz_name = _env(f"{prefix}TZ", "Europe/Moscow")

    if site_id == "moscow":
        if not api_key:
            api_key = _env("MANGO_VPBX_API_KEY")
        if not api_salt:
            api_salt = _env("MANGO_VPBX_API_SALT")
        if not line_number:
            line_number = _env(
                "MANGO_LINE_NUMBER",
                "sip:so1297co@vpbx400310395.mangosip.ru",
            )
        # Москва: только личка владельца, без группы «Москва Фили»
        if not label:
            label = "расшифровка звонков SOCO Москва"
        if not account:
            account = "16958477"

    if not api_key or not api_salt:
        return None
    if not label:
        label = f"расшифровка звонков SOCO {site_id}"
    return SiteConfig(
        site_id=site_id,
        label=label,
        account=account,
        api_key=api_key,
        api_salt=api_salt,
        line_number=line_number,
        group_chat_ids=group_ids,
        tz_name=tz_name or "Europe/Moscow",
    )


def load_sites() -> List[SiteConfig]:
    """Sites from MANGO_SITES=moscow,krasnoyarsk (default: moscow only)."""
    raw = _env("MANGO_SITES", "moscow")
    sites: List[SiteConfig] = []
    for part in raw.replace(";", ",").split(","):
        site_id = part.strip().lower()
        if not site_id:
            continue
        site = _site_from_env(site_id)
        if site:
            sites.append(site)
    if not sites:
        legacy = _site_from_env("moscow")
        if legacy:
            sites.append(legacy)
    return sites


def get_site(site_id: str) -> SiteConfig:
    site_id = site_id.strip().lower()
    for site in load_sites():
        if site.site_id == site_id:
            return site
    raise KeyError(f"Unknown site: {site_id}")
