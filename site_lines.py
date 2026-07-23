"""Per-site branch / extension rules (Krasnoyarsk add-ons)."""

from __future__ import annotations

import re
from typing import Optional

from mango_vpbx import CallRecord

# Красноярск: один номер 269-90-73, филиалы по добавочным
_KRAS_BRANCHES = {
    "05": "Новосибирская",
    "12": "Дубровинского",
    "25": "Весны",
}

_KRAS_EXCLUDED_EXT = frozenset({"97", "14", "105", "112", "197"})


def normalize_extension(ext: str) -> str:
    ext = (ext or "").strip()
    if not ext:
        return ""
    if ext.isdigit() and len(ext) <= 2:
        return ext.zfill(2)
    return ext


def _line_digits(call: CallRecord) -> str:
    return re.sub(r"\D", "", call.line_number or "")


def krasnoyarsk_branch(call: CallRecord) -> Optional[str]:
    """Return branch name or None if call should be ignored."""
    if _line_digits(call).endswith("2699078"):
        return None

    for raw in (call.to_extension, call.from_extension):
        ext = normalize_extension(raw)
        if not ext:
            continue
        if ext in _KRAS_EXCLUDED_EXT:
            return None
        if ext in _KRAS_BRANCHES:
            return _KRAS_BRANCHES[ext]
    return None


def is_tracked_call(site_id: str, call: CallRecord) -> bool:
    if site_id == "krasnoyarsk":
        return krasnoyarsk_branch(call) is not None
    return True


def branch_label(site_id: str, call: CallRecord) -> str:
    if site_id != "krasnoyarsk":
        return ""
    name = krasnoyarsk_branch(call)
    if not name:
        return ""
    ext = normalize_extension(call.to_extension or call.from_extension)
    return f"{name} (доб. {ext})"
