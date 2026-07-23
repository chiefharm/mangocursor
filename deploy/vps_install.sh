#!/bin/bash
set -euo pipefail

APP_DIR="/opt/mango-pipeline"
REPO_URL="${REPO_URL:-https://github.com/chiefharm/mangocursor.git}"
PYTHON_BIN="python3"

echo "==> Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip

echo "==> Preparing app directory: $APP_DIR"
mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

echo "==> Creating virtualenv..."
$PYTHON_BIN -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Creating folders..."
mkdir -p "$APP_DIR/data" "$APP_DIR/data/webhooks" "$APP_DIR/data/calls" "$APP_DIR/telegram_docx" "$APP_DIR/incoming"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "[WARN] Fill $APP_DIR/.env with TELEGRAM_* and MANGO_VPBX_* keys"
fi

echo "==> Installing systemd service..."
cat > /etc/systemd/system/mango-pipeline.service <<'UNIT'
[Unit]
Description=Mango daily call pipeline
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/mango-pipeline
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --mango-sync --mango-days 1
UNIT

echo "==> Installing timer (daily 10:00 MSK = 07:00 UTC on VPS)..."
cat > /etc/systemd/system/mango-pipeline.timer <<'TIMER'
[Unit]
Description=Run Mango pipeline daily at 10:00 MSK (07:00 UTC)

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable mango-pipeline.timer
systemctl restart mango-pipeline.timer

echo "==> Telegram connectivity check..."
if curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://api.telegram.org | grep -qE '^(200|302|404)$'; then
  echo "[OK] api.telegram.org reachable"
else
  echo "[WARN] api.telegram.org slow or blocked — pick another VPS region"
fi

echo "==> Done."
echo "1) Edit /opt/mango-pipeline/.env (Telegram + Mango API keys)"
echo "2) Test sync: /opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/mango_sync.py --base-dir /opt/mango-pipeline --days 1"
echo "3) Test pipeline: /opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --dry-run"
