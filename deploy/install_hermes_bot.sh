#!/bin/bash
# Hermes cursor-tg bridge (опционально, отдельный бот @hermes_cursor_agent_bot)
set -euo pipefail

INSTALL_DIR="/opt/cursor-tg"
DATA_DIR="/opt/cursor-tg/data"
REPO_URL="https://github.com/tb5z035i/cursor-tg.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git python3

if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

mkdir -p "$INSTALL_DIR" "$DATA_DIR"
if [ ! -d "$INSTALL_DIR/cursor-tg/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR/cursor-tg"
else
  git -C "$INSTALL_DIR/cursor-tg" pull --ff-only || true
fi

ENV_FILE="$INSTALL_DIR/.env"
if [ -f /opt/cursor-tg.env ]; then
  mv -f /opt/cursor-tg.env "$ENV_FILE"
elif [ ! -f "$ENV_FILE" ]; then
  cp "$INSTALL_DIR/cursor-tg/.env.example" "$ENV_FILE"
  echo "[WARN] Заполните $ENV_FILE (TELEGRAM_BOT_TOKEN, CURSOR_API_KEY)"
fi

docker build -t cursor-tg-connector "$INSTALL_DIR/cursor-tg"
docker rm -f cursor-tg 2>/dev/null || true
docker run -d \
  --name cursor-tg \
  --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -v "$DATA_DIR:/data" \
  cursor-tg-connector

echo "Hermes cursor-tg: docker logs -f cursor-tg"
