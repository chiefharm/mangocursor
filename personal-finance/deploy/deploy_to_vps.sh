#!/usr/bin/env bash
# Copy «Касса» to the European VPS from a machine that already has SSH
# (reads IP from deploy/vps.host, same as mango/tryon).
#
#   bash personal-finance/deploy/deploy_to_vps.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/personal-finance"
KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_DIR="${REMOTE_DIR:-/opt/personal-finance}"
PORT="${FINANCE_PORT:-8090}"

if [[ -z "${VPS_IP:-}" && -f "$ROOT/deploy/vps.host" ]]; then
  VPS_IP="$(tr -d '[:space:]' < "$ROOT/deploy/vps.host")"
fi
: "${VPS_IP:?Set VPS_IP or create deploy/vps.host}"

HOST="root@$VPS_IP"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
SCP=(scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

echo "==> SSH $HOST"
"${SSH[@]}" "$HOST" "echo SSH_OK && uname -a"

echo "==> upload $REMOTE_DIR"
"${SSH[@]}" "$HOST" "mkdir -p $REMOTE_DIR/app $REMOTE_DIR/static $REMOTE_DIR/deploy $REMOTE_DIR/tests $REMOTE_DIR/data/uploads"
"${SCP[@]}" "$APP/requirements.txt" "$APP/README.md" "$APP/.env.example" "$APP/pytest.ini" "$HOST:$REMOTE_DIR/"
"${SCP[@]}" "$APP/app/"*.py "$HOST:$REMOTE_DIR/app/"
"${SCP[@]}" "$APP/static/"* "$HOST:$REMOTE_DIR/static/"
"${SCP[@]}" "$APP/deploy/"* "$HOST:$REMOTE_DIR/deploy/"
"${SSH[@]}" "$HOST" "chmod +x $REMOTE_DIR/deploy/*.sh; sed -i 's/\r\$//' $REMOTE_DIR/deploy/*.sh $REMOTE_DIR/deploy/*.service"

echo "==> install on server"
"${SSH[@]}" "$HOST" "FINANCE_SKIP_FETCH=1 DEST=$REMOTE_DIR FINANCE_PORT=$PORT FINANCE_DOMAIN=${FINANCE_DOMAIN:-kassa.rost-i-razvitie.ru} bash $REMOTE_DIR/deploy/install_on_vps.sh"

echo
echo "Касса: https://kassa.rost-i-razvitie.ru  (если A-запись kassa → $VPS_IP уже стоит)"
echo "Пока DNS не обновился: http://$VPS_IP:$PORT"
