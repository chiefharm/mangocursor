#!/usr/bin/env python3
"""Resend last after_*.jpg to a MAX user to verify image delivery fix."""
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/soco-tryon")
os.chdir("/opt/soco-tryon")
from dotenv import load_dotenv

load_dotenv("/opt/soco-tryon/.env")
load_dotenv("/opt/mango-pipeline/.env")

from app import max_client

user_id = sys.argv[1] if len(sys.argv) > 1 else "198059339"
job = "d0bad903dedf488c961a203682700954"
path = Path(f"/opt/soco-tryon/data/results/{job}/after_1.jpg")
token = os.environ["MAX_BOT_TOKEN"].strip().strip('"')
pub = f"https://primerka.soco-salon.ru/api/results/{job}/{path.name}"
print("sending", path, "->", user_id)
max_client.send_text(token, "user_id", user_id, "Повторная отправка результата примерки (тест фикса):")
max_client.send_image_smart(token, "user_id", user_id, path, public_url=pub, caption="Вариант 1")
print("OK")
