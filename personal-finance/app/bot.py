"""Long-poll the finance Telegram group for buttons and /цель."""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

from .advice import parse_goal_amount, stance_label
from .report import money
from .store import FinanceStore
from . import telegram as tg

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _store() -> FinanceStore:
    data_dir = Path(os.getenv("FINANCE_DATA_DIR", str(BASE_DIR / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return FinanceStore(data_dir / "ledger.sqlite")


def handle_command(store: FinanceStore, text: str) -> str:
    parts = (text or "").strip().split()
    if not parts:
        return ""
    cmd = parts[0].split("@", 1)[0].lower()
    rest = " ".join(parts[1:])
    if cmd not in {"/цель", "/goal"}:
        return ""
    if not rest:
        goal = store.get_goal()
        if not goal:
            return "Цель не задана. Пример: /цель 80000 — хочу сальдо не меньше 80 000 ₽ в месяц."
        return f"Цель: сальдо {money(goal['amount'])} в месяц. Сменить: /цель 100000"
    amount = parse_goal_amount(rest)
    if amount is None:
        return "Не разобрал сумму. Пример: /цель 80000 или /цель 80к"
    store.set_goal(amount, "net")
    return f"Цель обновлена: сальдо {money(amount)} в месяц."


def handle_callback(store: FinanceStore, data: str) -> str:
    data = (data or "").strip()
    if data == "goal:ok":
        goal = store.get_goal()
        if not goal:
            return "Сначала задайте цель: /цель 80000"
        return f"Ок, цель {money(goal['amount'])} оставляем"
    if data == "goal:edit":
        return "Напишите /цель и сумму, например /цель 80000"
    if data.startswith("fb:"):
        parts = data.split(":")
        if len(parts) != 4:
            return "Не понял кнопку"
        _, digest_raw, idx_raw, code = parts
        stance = {"n": "normal", "c": "cut", "x": "not_expense"}.get(code)
        if not stance:
            return "Не понял кнопку"
        try:
            digest_id = int(digest_raw)
            idx = int(idx_raw)
        except ValueError:
            return "Не понял кнопку"
        payload = store.get_digest(digest_id)
        if not payload:
            return "Этот отчёт уже старый"
        spikes = payload.get("spikes") or []
        if idx < 0 or idx >= len(spikes):
            return "Нет такой статьи"
        name = str(spikes[idx].get("name") or "")
        store.set_stance(name, stance)
        return f"{name}: {stance_label(stance)}. Учту в следующем отчёте."
    return "Не понял кнопку"


def process_update(store: FinanceStore, update: dict) -> None:
    callback = update.get("callback_query")
    if callback:
        msg = callback.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if not tg.allowed_chat(chat):
            return
        toast = handle_callback(store, str(callback.get("data") or ""))
        tg.answer_callback(str(callback.get("id") or ""), toast)
        return
    message = update.get("message") or {}
    chat = (message.get("chat") or {}).get("id")
    if not tg.allowed_chat(chat):
        return
    text = str(message.get("text") or "")
    if not text.startswith("/"):
        return
    reply = handle_command(store, text)
    if reply:
        tg.send_message(reply)


def run_polling(store: FinanceStore | None = None) -> None:
    store = store or _store()
    if not tg.telegram_enabled():
        raise SystemExit("Telegram не настроен: FINANCE_TELEGRAM_BOT_TOKEN / CHAT_ID")
    print("[kassa-bot] polling group", tg.chat_id(), flush=True)
    while True:
        try:
            raw_off = store.get_setting("telegram_offset")
            offset = int(raw_off) if raw_off else None
            updates = tg.get_updates(offset, timeout=25)
            for update in updates:
                uid = int(update.get("update_id") or 0)
                store.set_setting("telegram_offset", str(uid + 1))
                try:
                    process_update(store, update)
                except Exception as exc:  # noqa: BLE001
                    print(f"[kassa-bot] update {uid}: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[kassa-bot] poll: {exc}", flush=True)
            time.sleep(3)


def main() -> None:
    run_polling()


if __name__ == "__main__":
    main()
