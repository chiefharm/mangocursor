"""When to ping the Telegram group after an import or after transfers are filed."""

from __future__ import annotations

from typing import Any

from .advice import Digest, build_digest
from .report import digest_keyboard, telegram_digest_message, telegram_pending_message
from .store import FinanceStore
from . import telegram as tg


def send_after_import(
    store: FinanceStore,
    *,
    imported: dict[str, Any],
    summary: dict[str, Any],
    previous: dict[str, Any] | None,
) -> str:
    """Return 'pending', 'full', or ''."""
    if not tg.telegram_enabled():
        return ""
    if int(summary.get("unreviewed_count") or 0) > 0:
        tg.send_message(
            telegram_pending_message(
                imported=imported,
                summary=summary,
                site_url=tg.site_url(),
            )
        )
        return "pending"
    send_full_digest(store, summary, previous)
    return "full"


def send_after_review_cleared(
    store: FinanceStore,
    *,
    summary: dict[str, Any],
    previous: dict[str, Any] | None,
) -> str:
    if not tg.telegram_enabled():
        return ""
    if int(summary.get("unreviewed_count") or 0) > 0:
        return ""
    send_full_digest(store, summary, previous)
    return "full"


def send_full_digest(
    store: FinanceStore,
    summary: dict[str, Any],
    previous: dict[str, Any] | None,
) -> Digest:
    digest = build_digest(
        summary,
        previous,
        goal=store.get_goal(),
        stances=store.stances(),
    )
    digest_id = store.save_digest(digest.to_dict())
    tg.send_message(
        telegram_digest_message(digest),
        reply_markup=digest_keyboard(digest_id, digest),
    )
    return digest
