# Finish migration to new Timeweb VPS (after restore_on_new_vps.sh).
# Usage: .\tryon-web\deploy\finish_migration.ps1
# Prerequisite: DNS A primerka.soco-salon.ru -> NEW IP (see deploy\vps.host)

param(
    [string]$VpsIp,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$Email = "p9050874245@gmail.com"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $Root "tryon-web\app\main.py"))) { $Root = Split-Path $PSScriptRoot -Parent }
$hostFile = Join-Path $Root "deploy\vps.host"
if (-not $VpsIp -and (Test-Path $hostFile)) { $VpsIp = (Get-Content $hostFile -Raw).Trim() }
if (-not $VpsIp) { throw "Set deploy\vps.host or -VpsIp" }

$Host_ = "root@$VpsIp"
$Tryon = Join-Path $Root "tryon-web"

Write-Host "==> Deploy latest code to $Host_" -ForegroundColor Cyan
scp -i $SshKey (Join-Path $Tryon "app\*.py") "${Host_}:/opt/soco-tryon/app/"
scp -i $SshKey (Join-Path $Tryon "static\index.html") (Join-Path $Tryon "static\app.js") (Join-Path $Tryon "static\styles.css") "${Host_}:/opt/soco-tryon/static/"
scp -i $SshKey (Join-Path $Root "PROJECT_MEMORY.md") (Join-Path $Root "SESSION_LOG.md") (Join-Path $Root "CODE_MAP.md") (Join-Path $Root "AGENTS.md") "${Host_}:/opt/mango-pipeline/"

Write-Host "==> Restart + certbot (needs DNS on this IP)" -ForegroundColor Cyan
ssh -i $SshKey $Host_ @"
set -e
sed -i 's/\r$//' /opt/soco-tryon/app/*.py /opt/soco-tryon/deploy/*.py 2>/dev/null || true
systemctl restart soco-tryon
sleep 2
curl -sS http://127.0.0.1:18088/api/health
echo
if ! ls /etc/letsencrypt/live/primerka.soco-salon.ru/fullchain.pem 2>/dev/null; then
  certbot --nginx -d primerka.soco-salon.ru --non-interactive --agree-tos -m $Email --redirect || echo 'certbot failed — check DNS A record'
fi
"@

Write-Host "==> Register TG/MAX webhooks (from old VPS if new blocks Telegram API)" -ForegroundColor Cyan
ssh -i $SshKey $Host_ "/opt/soco-tryon/.venv/bin/python /opt/soco-tryon/deploy/register_bot_webhooks.py" 2>$null
if ($LASTEXITCODE -ne 0) {
    $old = "72.56.27.174"
    Write-Host "Retry webhooks via old VPS $old" -ForegroundColor Yellow
    scp -i $SshKey (Join-Path $Tryon "deploy\register_bot_webhooks.py") "root@${old}:/tmp/register_bot_webhooks.py"
    ssh -i $SshKey "root@$old" "python3 /tmp/register_bot_webhooks.py" 2>$null
}

Write-Host "DONE. Check: https://primerka.soco-salon.ru/api/health" -ForegroundColor Green
