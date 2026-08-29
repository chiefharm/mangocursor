#!/usr/bin/env bash
# Install / update «Касса» on the European VPS. Run as root.
#
# One line in Timeweb console (repo already lives at /opt/mango-pipeline):
#   git -C /opt/mango-pipeline fetch origin cursor/personal-finance-web-2b09 && \
#   git -C /opt/mango-pipeline show origin/cursor/personal-finance-web-2b09:personal-finance/deploy/install_on_vps.sh | bash
#
# Does not touch mango-pipeline systemd, groups, or salon Telegram chats.
set -euo pipefail

BRANCH="${FINANCE_GIT_BRANCH:-cursor/personal-finance-web-2b09}"
REPO="${MANGO_REPO:-/opt/mango-pipeline}"
DEST="${DEST:-/opt/personal-finance}"
PORT="${FINANCE_PORT:-8090}"
SKIP_FETCH="${FINANCE_SKIP_FETCH:-0}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Нужен root" >&2
  exit 1
fi

copy_tree() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude '.env' --exclude 'data/' --exclude '.venv/' "$src/" "$dest/"
  else
    find "$src" -mindepth 1 -maxdepth 1 ! -name '.env' ! -name 'data' ! -name '.venv' \
      -exec cp -a {} "$dest/" \;
  fi
}

if [[ "$SKIP_FETCH" != "1" ]]; then
  if [[ ! -d "$REPO/.git" ]]; then
    echo "Нет git-репозитория в $REPO — скопируйте файлы и повторите с FINANCE_SKIP_FETCH=1" >&2
    exit 1
  fi
  echo "==> git fetch origin $BRANCH"
  git -C "$REPO" fetch origin "$BRANCH"
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  git -C "$REPO" archive "origin/$BRANCH" personal-finance | tar -x -C "$tmpdir"
  if [[ ! -f "$tmpdir/personal-finance/app/main.py" ]]; then
    echo "В ветке $BRANCH нет personal-finance/" >&2
    exit 1
  fi
  echo "==> copy to $DEST"
  mkdir -p "$DEST/data/uploads"
  copy_tree "$tmpdir/personal-finance" "$DEST"
else
  if [[ ! -f "$DEST/app/main.py" ]]; then
    echo "Нет $DEST/app/main.py" >&2
    exit 1
  fi
  mkdir -p "$DEST/data/uploads"
fi

echo "==> python venv"
export DEBIAN_FRONTEND=noninteractive
if ! python3 -c "import venv" 2>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3-venv python3-pip
fi
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q --upgrade pip
"$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"

if [[ ! -f "$DEST/.env" ]]; then
  echo "==> .env"
  PASS="$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(16)))')"
  TOKEN=""
  CHAT=""
  if [[ -f "$REPO/.env" ]]; then
    TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$REPO/.env" | head -1 | cut -d= -f2- | tr -d "\"'")"
    CHAT="$(grep -E '^TELEGRAM_CHAT_ID=' "$REPO/.env" | head -1 | cut -d= -f2- | tr -d "\"'")"
  fi
  TG_ON=0
  if [[ -n "$TOKEN" && -n "$CHAT" ]]; then
    TG_ON=1
  fi
  cat > "$DEST/.env" <<EOF
FINANCE_PASSWORD=$PASS
FINANCE_PORT=$PORT
FINANCE_TELEGRAM_ENABLED=$TG_ON
FINANCE_TELEGRAM_BOT_TOKEN=$TOKEN
FINANCE_TELEGRAM_CHAT_ID=$CHAT
EOF
  chmod 600 "$DEST/.env"
  umask 077
  printf '%s\n' "$PASS" > "$DEST/data/.initial-password"
  chmod 600 "$DEST/data/.initial-password"
else
  PASS=""
  echo "==> keep existing $DEST/.env"
fi

sed -i 's/\r$//' "$DEST/deploy/personal-finance.service" || true
cp "$DEST/deploy/personal-finance.service" /etc/systemd/system/personal-finance.service
systemctl daemon-reload
systemctl enable --now personal-finance
systemctl restart personal-finance
sleep 2
systemctl --no-pager --full status personal-finance | head -n 16 || true

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" || true
fi

PUB="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
if [[ -z "$PUB" ]]; then
  PUB="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo
echo "[DONE] Касса: http://${PUB}:$PORT"
if [[ -n "$PASS" ]]; then
  echo "Пароль входа (сохраните, в git его нет): $PASS"
elif [[ -f "$DEST/data/.initial-password" ]]; then
  echo "Пароль уже задан. Посмотреть на сервере: cat $DEST/data/.initial-password"
fi
curl -sS --max-time 5 "http://127.0.0.1:${PORT}/api/health" || true
echo
