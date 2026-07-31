#!/usr/bin/env bash
# Deploy SOCO tryon-web to VPS (from a machine that has SSH access).
# Usage:
#   export VPS_IP=1.2.3.4
#   export PERFECTCORP_API_KEY='...'   # optional if tryon-web/.env exists
#   bash tryon-web/deploy/deploy_to_vps.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TRYON="$ROOT/tryon-web"
KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/opt/soco-tryon}"
PORT="${PORT:-8088}"

if [[ -z "${VPS_IP:-}" && -f "$ROOT/deploy/vps.host" ]]; then
  VPS_IP="$(tr -d '[:space:]' < "$ROOT/deploy/vps.host")"
fi
: "${VPS_IP:?Set VPS_IP or create deploy/vps.host}"

HOST="root@$VPS_IP"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
SCP=(scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

echo "==> SSH check $HOST"
"${SSH[@]}" "$HOST" "echo SSH_OK && uname -a"

echo "==> Upload"
"${SSH[@]}" "$HOST" "mkdir -p $REMOTE_DIR/app $REMOTE_DIR/static $REMOTE_DIR/deploy $REMOTE_DIR/data"
"${SCP[@]}" "$TRYON/requirements.txt" "$TRYON/README.md" "$TRYON/.env.example" "$HOST:$REMOTE_DIR/"
"${SCP[@]}" "$TRYON/app/"*.py "$HOST:$REMOTE_DIR/app/"
"${SCP[@]}" "$TRYON/static/"* "$HOST:$REMOTE_DIR/static/"
"${SCP[@]}" "$TRYON/deploy/soco-tryon.service" "$HOST:$REMOTE_DIR/deploy/"

if [[ -f "$TRYON/.env" ]]; then
  "${SCP[@]}" "$TRYON/.env" "$HOST:$REMOTE_DIR/.env"
  "${SSH[@]}" "$HOST" "chmod 600 $REMOTE_DIR/.env"
elif [[ -n "${PERFECTCORP_API_KEY:-}" ]]; then
  "${SSH[@]}" "$HOST" "printf 'PERFECTCORP_API_KEY=%s\n' \"$PERFECTCORP_API_KEY\" > $REMOTE_DIR/.env && chmod 600 $REMOTE_DIR/.env"
else
  "${SSH[@]}" "$HOST" "test -f $REMOTE_DIR/.env || cp $REMOTE_DIR/.env.example $REMOTE_DIR/.env; chmod 600 $REMOTE_DIR/.env"
fi

echo "==> Install + start"
"${SSH[@]}" "$HOST" "bash -s" <<EOF
set -e
cd $REMOTE_DIR
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
sed -i 's/\r\$//' deploy/soco-tryon.service
cp deploy/soco-tryon.service /etc/systemd/system/soco-tryon.service
systemctl daemon-reload
systemctl enable --now soco-tryon
systemctl restart soco-tryon
sleep 2
systemctl --no-pager --full status soco-tryon | head -n 20
curl -s http://127.0.0.1:$PORT/api/health || true
echo
command -v ufw >/dev/null && ufw allow $PORT/tcp || true
EOF

echo
echo "[DONE] http://$VPS_IP:$PORT"
echo "Health: http://$VPS_IP:$PORT/api/health"
