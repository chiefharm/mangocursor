#!/usr/bin/env bash
# Put «Касса» behind nginx + Let's Encrypt on a hostname.
# Does not change DNS. Add an A-record first, then run this as root.
#
#   FINANCE_DOMAIN=kassa.rost-i-razvitie.ru bash /opt/personal-finance/deploy/setup_domain.sh
#
# Apex rost-i-razvitie.ru is a live Vigbo site (центр «Рост и Развитие»).
# Do not point that name here unless FINANCE_DOMAIN_FORCE=1.
set -euo pipefail

DEST="${DEST:-/opt/personal-finance}"
PORT="${FINANCE_PORT:-8090}"
DOMAIN="${FINANCE_DOMAIN:-kassa.rost-i-razvitie.ru}"
FORCE="${FINANCE_DOMAIN_FORCE:-0}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Нужен root" >&2
  exit 1
fi

DOMAIN="${DOMAIN,,}"
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN%%/*}"

if [[ -z "$DOMAIN" || "$DOMAIN" == *' '* ]]; then
  echo "Пустой FINANCE_DOMAIN" >&2
  exit 1
fi

if [[ "$FORCE" != "1" && ( "$DOMAIN" == "rost-i-razvitie.ru" || "$DOMAIN" == "www.rost-i-razvitie.ru" ) ]]; then
  echo "На rost-i-razvitie.ru уже сайт психологического центра (Vigbo)." >&2
  echo "Кассу вешаем на kassa.rost-i-razvitie.ru, чтобы не снести основной сайт." >&2
  echo "Если точно нужен корень домена: FINANCE_DOMAIN_FORCE=1" >&2
  exit 1
fi

PUB="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
if [[ -z "$PUB" ]]; then
  PUB="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo "==> nginx for $DOMAIN → 127.0.0.1:$PORT"
export DEBIAN_FRONTEND=noninteractive
if ! command -v nginx >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq nginx
fi
if ! command -v certbot >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq certbot python3-certbot-nginx
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp || true
  ufw allow 443/tcp || true
fi

site="/etc/nginx/sites-available/kassa"
cat > "$site" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sfn "$site" /etc/nginx/sites-enabled/kassa
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

if [[ -f "$DEST/.env" && -x "$DEST/.venv/bin/python" ]]; then
  cd "$DEST"
  "$DEST/.venv/bin/python" - <<PY || true
from app.chats import upsert_env
from pathlib import Path
upsert_env(Path("$DEST") / ".env", "FINANCE_DOMAIN", "$DOMAIN")
upsert_env(Path("$DEST") / ".env", "FINANCE_SITE_URL", "https://$DOMAIN")
PY
fi

echo
echo "DNS: в панели Vigbo / регистраторе добавьте A-запись:"
echo "  имя:  kassa"
echo "  тип:  A"
echo "  значение: ${PUB:-IP_VPS}"
echo "Корень rost-i-razvitie.ru не трогайте — там сайт центра."
echo

pointed=0
if [[ -n "$PUB" ]]; then
  resolved="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
  if [[ "$resolved" == "$PUB" ]]; then
    pointed=1
  fi
fi

if [[ "$pointed" -eq 1 ]]; then
  echo "==> DNS уже смотрит сюда — выпускаю сертификат"
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
  echo
  echo "[DONE] Касса: https://${DOMAIN}"
else
  echo "[WAIT] Пока $DOMAIN не указывает на ${PUB:-этот сервер}."
  echo "После A-записи подождите 2–10 минут и повторите:"
  echo "  FINANCE_DOMAIN=$DOMAIN bash $DEST/deploy/setup_domain.sh"
  echo
  echo "Пока так: http://${PUB:-IP}:$PORT"
fi
