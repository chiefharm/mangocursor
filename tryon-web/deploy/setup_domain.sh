#!/usr/bin/env bash
# Run on VPS after DNS A-record points here (for HTTPS).
# Usage: DOMAIN=tryon.soco-salon.ru bash /opt/soco-tryon/deploy/setup_domain.sh
set -euo pipefail

DOMAIN="${DOMAIN:-tryon.soco-salon.ru}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF_SRC="$ROOT/deploy/nginx-tryon.conf"
CONF_DST="/etc/nginx/sites-available/soco-tryon"

if [[ ! -f "$CONF_SRC" ]]; then
  echo "Missing $CONF_SRC" >&2
  exit 1
fi

sed "s/server_name tryon\\.soco-salon\\.ru;/server_name ${DOMAIN};/" "$CONF_SRC" > "$CONF_DST"
ln -sfn "$CONF_DST" /etc/nginx/sites-enabled/soco-tryon

# Open legacy port in firewall if ufw is active
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
  ufw allow 8088/tcp || true
  ufw allow 80/tcp || true
  ufw allow 443/tcp || true
fi

nginx -t
systemctl reload nginx

echo "Nginx tryon enabled (legacy :8088 + http://${DOMAIN})."

if [[ "${SKIP_CERTBOT:-0}" == "1" ]]; then
  echo "SKIP_CERTBOT=1 — HTTPS not requested."
  exit 0
fi

# Certbot needs DNS already pointing here
if ! command -v certbot >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y certbot python3-certbot-nginx
fi

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email \
  || certbot --nginx -d "$DOMAIN"

echo "OK: https://${DOMAIN}"
