#!/bin/bash
# Restore soco-tryon + mango-pipeline onto a fresh Timeweb VPS.
# Usage (on NEW server as root), after archives are in /root/migrate/:
#   bash /root/migrate/restore_on_new_vps.sh
set -euo pipefail

MIGRATE_DIR="${1:-/root/migrate}"
export DEBIAN_FRONTEND=noninteractive

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv python3-pip certbot python3-certbot-nginx \
  curl ca-certificates ufw

echo "==> Extract soco-tryon"
rm -rf /opt/soco-tryon
tar -xzf "$MIGRATE_DIR/soco-tryon.tgz" -C /opt
# Recreate venv if missing/broken
if [[ ! -x /opt/soco-tryon/.venv/bin/uvicorn ]]; then
  python3 -m venv /opt/soco-tryon/.venv
  /opt/soco-tryon/.venv/bin/pip install -U pip wheel
  if [[ -f /opt/soco-tryon/requirements.txt ]]; then
    /opt/soco-tryon/.venv/bin/pip install -r /opt/soco-tryon/requirements.txt
  else
    /opt/soco-tryon/.venv/bin/pip install fastapi uvicorn[standard] python-multipart httpx pillow python-dotenv
  fi
fi

echo "==> Extract mango-pipeline"
rm -rf /opt/mango-pipeline
tar -xzf "$MIGRATE_DIR/mango-pipeline.tgz" -C /opt
if [[ ! -x /opt/mango-pipeline/.venv/bin/python ]]; then
  python3 -m venv /opt/mango-pipeline/.venv || true
  if [[ -f /opt/mango-pipeline/requirements.txt ]]; then
    /opt/mango-pipeline/.venv/bin/pip install -r /opt/mango-pipeline/requirements.txt || true
  fi
fi

echo "==> Systemd units"
if [[ -f "$MIGRATE_DIR/etc/soco-tryon.service" ]]; then
  cp -a "$MIGRATE_DIR/etc/soco-tryon.service" /etc/systemd/system/
fi
cp -a "$MIGRATE_DIR"/etc/mango-pipeline*.service "$MIGRATE_DIR"/etc/mango-pipeline*.timer /etc/systemd/system/ 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now soco-tryon.service
systemctl enable mango-pipeline.timer mango-pipeline-kras.timer 2>/dev/null || true
systemctl start mango-pipeline.timer mango-pipeline-kras.timer 2>/dev/null || true

echo "==> Nginx for primerka.soco-salon.ru"
cat >/etc/nginx/sites-available/soco-tryon <<'NGINX'
upstream soco_tryon {
    server 127.0.0.1:18088;
    keepalive 8;
}

server {
    listen 8088;
    listen [::]:8088;
    server_name _;
    client_max_body_size 12m;
    location / {
        proxy_pass http://soco_tryon;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name primerka.soco-salon.ru;
    client_max_body_size 12m;
    location / {
        proxy_pass http://soco_tryon;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/soco-tryon /etc/nginx/sites-enabled/soco-tryon
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> Firewall"
ufw allow OpenSSH || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
ufw allow 8088/tcp || true
ufw --force enable || true

echo "==> Health"
sleep 2
systemctl --no-pager --full status soco-tryon | head -20
curl -sS http://127.0.0.1:18088/api/health || curl -sS http://127.0.0.1:18088/ || true
echo
echo "DONE. Next: point DNS A primerka.soco-salon.ru -> this VPS IP, then:"
echo "  certbot --nginx -d primerka.soco-salon.ru --non-interactive --agree-tos -m you@example.com --redirect"
