"""Discover Telegram chats the bot can see and bind the finance group."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import telegram as tg

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DEFAULT_GROUP = "учет финансов"


def _norm(text: str) -> str:
    t = (text or "").casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", t).strip()


def chats_from_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in updates:
        for key in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
            blob = item.get(key)
            if not isinstance(blob, dict):
                continue
            chat = blob.get("chat") if isinstance(blob.get("chat"), dict) else blob
            if not isinstance(chat, dict) or chat.get("id") is None:
                continue
            cid = str(chat["id"])
            title = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
            found[cid] = {
                "id": cid,
                "type": chat.get("type") or "",
                "title": str(title),
            }
    return list(found.values())


def find_group(chats: list[dict[str, Any]], name: str = DEFAULT_GROUP) -> dict[str, Any] | None:
    want = _norm(name)
    groups = [c for c in chats if c.get("type") in {"group", "supergroup"}]
    for chat in groups:
        if _norm(chat.get("title") or "") == want:
            return chat
    for chat in groups:
        title = _norm(chat.get("title") or "")
        if want in title or title in want:
            return chat
    return None


def upsert_env(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    done = False
    out: list[str] = []
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def bind_group(name: str = DEFAULT_GROUP, *, notify: bool = False, env_path: Path | None = None) -> dict[str, Any]:
    env_path = env_path or ENV_PATH
    load_dotenv(env_path)
    if not tg.token():
        raise SystemExit("Нет FINANCE_TELEGRAM_BOT_TOKEN — сначала токен бота в .env")
    me = tg.get_me().get("result") or {}
    username = me.get("username") or "?"
    updates = tg.get_updates(None, timeout=0)
    chats = chats_from_updates(updates)
    group = find_group(chats, name)
    if not group:
        titles = ", ".join(f"{c['title']} ({c['id']})" for c in chats) or "пусто"
        raise SystemExit(
            f"Группу «{name}» бот @{username} пока не видит. "
            "Напишите в ней любое сообщение (или /цель) и запустите снова. "
            f"Что видно: {titles}"
        )
    upsert_env(env_path, "FINANCE_TELEGRAM_CHAT_ID", group["id"])
    upsert_env(env_path, "FINANCE_TELEGRAM_ENABLED", "1")
    os.environ["FINANCE_TELEGRAM_CHAT_ID"] = group["id"]
    os.environ["FINANCE_TELEGRAM_ENABLED"] = "1"
    if notify:
        tg.send_message(
            "<b>Касса</b> подключена к этой группе.\n"
            "Задайте цель: /цель 80000\n"
            "Отчёты придут после загрузки выписки на сайте.",
            chat=group["id"],
        )
    return {"bot": username, **group}


def main() -> None:
    load_dotenv(ENV_PATH)
    parser = argparse.ArgumentParser(description="Привязать Telegram-группу кассы")
    parser.add_argument("--bind", default="", help="Название группы, например «учет финансов»")
    parser.add_argument("--notify", action="store_true", help="Отправить тестовое сообщение")
    parser.add_argument("--list", action="store_true", help="Только показать чаты")
    args = parser.parse_args()
    if not tg.token():
        raise SystemExit("Нет FINANCE_TELEGRAM_BOT_TOKEN")
    if args.list or not args.bind:
        me = tg.get_me().get("result") or {}
        print(f"Бот: @{me.get('username')}")
        chats = chats_from_updates(tg.get_updates(None, timeout=0))
        if not chats:
            print("Чатов нет. Напишите в группе с ботом и повторите.")
            return
        for chat in chats:
            mark = " ← группа" if chat["type"] in {"group", "supergroup"} else ""
            print(f"  {chat['id']}  {chat['type']}  {chat['title']}{mark}")
        if not args.bind:
            return
    info = bind_group(args.bind, notify=args.notify)
    print(f"Ок: @{info['bot']} → {info['title']} id={info['id']}")


if __name__ == "__main__":
    main()
