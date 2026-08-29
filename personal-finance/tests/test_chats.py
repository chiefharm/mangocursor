from app.chats import chats_from_updates, find_group, upsert_env


def test_find_finance_group_ignores_private() -> None:
    updates = [
        {
            "my_chat_member": {
                "chat": {"id": -100123, "title": "учет финансов", "type": "supergroup"}
            }
        },
        {"message": {"chat": {"id": 9050874245, "first_name": "Егор", "type": "private"}}},
        {"message": {"chat": {"id": -200, "title": "Москва Фили", "type": "group"}}},
    ]
    chats = chats_from_updates(updates)
    group = find_group(chats, "учёт финансов")
    assert group is not None
    assert group["id"] == "-100123"


def test_upsert_env(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("FINANCE_PASSWORD=x\nFINANCE_TELEGRAM_CHAT_ID=old\n", encoding="utf-8")
    upsert_env(path, "FINANCE_TELEGRAM_CHAT_ID", "-1001")
    text = path.read_text(encoding="utf-8")
    assert "FINANCE_TELEGRAM_CHAT_ID=-1001" in text
    assert "FINANCE_PASSWORD=x" in text
    assert "old" not in text
