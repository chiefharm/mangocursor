# Deploy Telegram API relay to Amsterdam VPS.
# Usage: .\tryon-web\deploy\tg_relay\deploy_to_ams.ps1

param(
    [string]$AmsIp,
    [string]$NskIp,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RelaySecret = "soco-tg-relay"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
if (-not (Test-Path (Join-Path $Root "deploy\vps.host"))) {
    $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
}
$euFile = Join-Path $Root "deploy\vps.host.eu"
$hostFile = Join-Path $Root "deploy\vps.host"
if (-not $AmsIp -and (Test-Path $euFile)) { $AmsIp = (Get-Content $euFile -Raw).Trim() }
if (-not $NskIp -and (Test-Path $hostFile)) { $NskIp = (Get-Content $hostFile -Raw).Trim() }
if (-not $AmsIp) { throw "Set deploy/vps.host.eu or -AmsIp" }
if (-not $NskIp) { $NskIp = "147.45.102.129" }

$HostAms = "root@$AmsIp"
$HostNsk = "root@$NskIp"
$LocalRelay = $PSScriptRoot

Write-Host "==> Deploy relay to Amsterdam $AmsIp" -ForegroundColor Cyan
ssh -i $SshKey -o ConnectTimeout=20 $HostAms "mkdir -p /opt/soco-tg-relay"
scp -i $SshKey (Join-Path $LocalRelay "app.py") (Join-Path $LocalRelay "requirements.txt") (Join-Path $LocalRelay "register_webhook_via_relay.py") (Join-Path $LocalRelay "soco-tg-relay.service") "${HostAms}:/opt/soco-tryon-tmp/" 2>$null
# put files directly
scp -i $SshKey (Join-Path $LocalRelay "app.py") (Join-Path $LocalRelay "requirements.txt") (Join-Path $LocalRelay "register_webhook_via_relay.py") "${HostAms}:/opt/soco-tg-relay/"
scp -i $SshKey (Join-Path $LocalRelay "soco-tg-relay.service") "${HostAms}:/etc/systemd/system/soco-tg-relay.service"

Write-Host "==> Install venv + enable service" -ForegroundColor Cyan
ssh -i $SshKey $HostAms @"
set -e
cd /opt/soco-tg-relay
sed -i 's/\r`$//' app.py requirements.txt register_webhook_via_relay.py /etc/systemd/system/soco-tg-relay.service
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -U pip wheel
.venv/bin/pip install -q -r requirements.txt
# pull TELEGRAM token from mango-pipeline if relay .env missing
if [ ! -f .env ]; then
  touch .env
fi
if ! grep -q '^TRYON_TG_RELAY_SECRET=' .env 2>/dev/null; then
  echo "TRYON_TG_RELAY_SECRET=$RelaySecret" >> .env
fi
if ! grep -qE '^(TELEGRAM_BOT_TOKEN|TRYON_TELEGRAM_BOT_TOKEN)=' .env 2>/dev/null; then
  if [ -f /opt/mango-pipeline/.env ]; then
    grep -E '^(TELEGRAM_BOT_TOKEN|TRYON_TELEGRAM_BOT_TOKEN)=' /opt/mango-pipeline/.env >> .env || true
  fi
fi
chmod 600 .env
# firewall: only NSK may hit relay
if command -v ufw >/dev/null 2>&1; then
  ufw allow from $NskIp to any port 18100 proto tcp || true
  ufw allow from 127.0.0.1 to any port 18100 proto tcp || true
fi
systemctl daemon-reload
systemctl enable --now soco-tg-relay
systemctl restart soco-tg-relay
sleep 1
systemctl is-active soco-tg-relay
curl -sS http://127.0.0.1:18100/health
echo
"@

Write-Host "==> Configure NSK tryon to use relay" -ForegroundColor Cyan
$relayLine1 = "TRYON_TG_RELAY_URL=http://${AmsIp}:18100"
$relayLine2 = "TRYON_TG_RELAY_SECRET=$RelaySecret"
ssh -i $SshKey $HostNsk @"
set -e
ENV=/opt/soco-tryon/.env
touch `$ENV
grep -v '^TRYON_TG_RELAY_URL=' `$ENV > `$ENV.tmp || true
grep -v '^TRYON_TG_RELAY_SECRET=' `$ENV.tmp > `$ENV || true
rm -f `$ENV.tmp
echo '$relayLine1' >> `$ENV
echo '$relayLine2' >> `$ENV
chmod 600 `$ENV
grep TRYON_TG_RELAY `$ENV | sed 's/=.*/=***/'
"@

Write-Host "==> Deploy bot_delivery.py to NSK + restart" -ForegroundColor Cyan
$Tryon = Join-Path $Root "tryon-web"
scp -i $SshKey (Join-Path $Tryon "app\bot_delivery.py") "${HostNsk}:/opt/soco-tryon/app/"
ssh -i $SshKey $HostNsk "sed -i 's/\r`$//' /opt/soco-tryon/app/bot_delivery.py; systemctl restart soco-tryon; sleep 1; systemctl is-active soco-tryon; curl -sS http://127.0.0.1:18088/api/health; echo"

Write-Host "==> Register webhook via Amsterdam relay" -ForegroundColor Cyan
ssh -i $SshKey $HostAms "/opt/soco-tg-relay/.venv/bin/python /opt/soco-tg-relay/register_webhook_via_relay.py"

Write-Host "==> Smoke: NSK -> AMS relay getMe" -ForegroundColor Cyan
ssh -i $SshKey $HostNsk @"
python3 - <<'PY'
import json, os, urllib.request
from pathlib import Path
env = {}
for line in Path('/opt/soco-tryon/.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"')
relay=env.get('TRYON_TG_RELAY_URL','').rstrip('/')
secret=env.get('TRYON_TG_RELAY_SECRET','soco-tg-relay')
req=urllib.request.Request(relay+'/bot/getMe', headers={'X-Relay-Secret': secret}, method='GET')
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.read().decode())
PY
"@

Write-Host "DONE. Relay: http://${AmsIp}:18100  Webhook: primerka -> NSK, sends via AMS" -ForegroundColor Green
