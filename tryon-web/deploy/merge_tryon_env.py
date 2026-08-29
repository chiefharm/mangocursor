#!/usr/bin/env python3
from pathlib import Path

env_path = Path("/opt/soco-tryon/.env")
mango = Path("/opt/mango-pipeline/.env")
cur = {}
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cur[k.strip()] = v.strip()

src = {}
for line in mango.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    src[k.strip()] = v.strip()

for k in (
    "MAX_BOT_TOKEN",
    "MAX_OWNER_USER_ID",
    "MAX_OWNER_CHAT_ID",
    "MAX_KRASNOYARSK_CHAT_ID",
    "MAX_MOSCOW_CHAT_ID",
    "MAX_TLS_INSECURE",
    "MAX_API_BASE",
):
    if k in src and not cur.get(k):
        cur[k] = src[k]

cur.setdefault("LEAD_EMAIL_TO", "p9050874245@gmail.com")
cur.setdefault("SMTP_HOST", "smtp.gmail.com")
cur.setdefault("SMTP_PORT", "587")
cur.setdefault("SMTP_STARTTLS", "1")
cur.setdefault("MAX_TLS_INSECURE", "1")

if not cur.get("TRYON_MAX_CHAT_IDS") and cur.get("MAX_KRASNOYARSK_CHAT_ID"):
    parts = []
    if cur.get("MAX_OWNER_USER_ID"):
        parts.append("user:" + cur["MAX_OWNER_USER_ID"].strip('"'))
    parts.append(cur["MAX_KRASNOYARSK_CHAT_ID"].strip('"'))
    cur["TRYON_MAX_CHAT_IDS"] = ",".join(parts)

env_path.write_text("\n".join(f"{k}={v}" for k, v in cur.items()) + "\n", encoding="utf-8")
print("has_max", bool(cur.get("MAX_BOT_TOKEN")))
print("has_smtp_pass", bool(cur.get("SMTP_PASSWORD")))
print("has_smtp_user", bool(cur.get("SMTP_USER")))
print("lead_email", cur.get("LEAD_EMAIL_TO"))
print("tryon_targets_set", bool(cur.get("TRYON_MAX_CHAT_IDS")))
