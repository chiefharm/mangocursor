#!/bin/bash
cd /opt/mango-pipeline
export $(grep -v '^#' .env | xargs)
.venv/bin/python <<'PY'
import os
from telegram_notify import parse_chat_ids, tg_broadcast_message

msg = """Период 25 июня — 2 июля

В Mango за эти дни:
• 25.06 — 4 звонка с записью (расшифровки выше)
• 26.06–28.06, 01–02.07 — звонки есть, но записей разговоров нет
• 29–30.06 — данные из Mango временно недоступны

Без записи расшифровку сделать нельзя."""
tg_broadcast_message(os.environ["TELEGRAM_BOT_TOKEN"], parse_chat_ids(), msg)
print("period note sent")
PY
