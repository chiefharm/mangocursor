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
mkdir -p "$APP_DIR/data" "$APP_DIR/telegram_docx" "$APP_DIR/incoming"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "[WARN] Fill $APP_DIR/.env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
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
ExecStart=/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --git-pull
UNIT

echo "==> Installing timer (daily 20:00 MSK ~= 17:00 UTC)..."
cat > /etc/systemd/system/mango-pipeline.timer <<'TIMER'
[Unit]
Description=Run Mango pipeline daily

[Timer]
OnCalendar=*-*-* 17:00:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable mango-pipeline.timer
systemctl restart mango-pipeline.timer

echo "==> Done."
echo "1) Edit /opt/mango-pipeline/.env"
echo "2) Put new HTML calls into /opt/mango-pipeline (or push to GitHub and use --git-pull)"
echo "3) Test run: /opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/daily_pipeline.py --base-dir /opt/mango-pipeline --dry-run"
echo "4) Real run: systemctl start mango-pipeline.service"
