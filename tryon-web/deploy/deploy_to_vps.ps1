# Deploy SOCO tryon-web to VPS in one go.
# Usage:
#   .\tryon-web\deploy\deploy_to_vps.ps1
#   .\tryon-web\deploy\deploy_to_vps.ps1 -VpsIp 1.2.3.4
# Optional: set PERFECTCORP_API_KEY in tryon-web\.env before running.

param(
    [string]$VpsIp,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RemoteDir = "/opt/soco-tryon",
    [int]$Port = 8088
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $Root "tryon-web\app\main.py"))) {
    $Root = Split-Path $PSScriptRoot -Parent
}
$TryonLocal = Join-Path $Root "tryon-web"
$hostFile = Join-Path $Root "deploy\vps.host"

if (-not $VpsIp -and (Test-Path $hostFile)) {
    $VpsIp = (Get-Content $hostFile -Raw).Trim()
}
if (-not $VpsIp) {
    throw "Укажите -VpsIp или создайте deploy\vps.host"
}
if (-not (Test-Path $SshKey)) {
    throw "SSH-ключ не найден: $SshKey"
}
if (-not (Test-Path (Join-Path $TryonLocal "app\main.py"))) {
    throw "Не найден tryon-web: $TryonLocal"
}

$Host_ = "root@$VpsIp"
Write-Host "==> SSH check $Host_" -ForegroundColor Cyan
ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new $Host_ "echo SSH_OK && uname -a" | Write-Host

Write-Host "==> Create remote dir $RemoteDir" -ForegroundColor Cyan
ssh -i $SshKey $Host_ "mkdir -p $RemoteDir"

Write-Host "==> Upload tryon-web files" -ForegroundColor Cyan
$files = @(
    "requirements.txt", "README.md", ".env.example", ".gitignore",
    "app", "static", "deploy"
) | ForEach-Object { Join-Path $TryonLocal $_ } | Where-Object { Test-Path $_ }

# Ensure remote structure
ssh -i $SshKey $Host_ "mkdir -p $RemoteDir/app $RemoteDir/static $RemoteDir/deploy $RemoteDir/data"

scp -i $SshKey (Join-Path $TryonLocal "requirements.txt") "${Host_}:${RemoteDir}/"
scp -i $SshKey (Join-Path $TryonLocal "README.md") "${Host_}:${RemoteDir}/"
scp -i $SshKey (Join-Path $TryonLocal ".env.example") "${Host_}:${RemoteDir}/"
scp -i $SshKey (Join-Path $TryonLocal "app\*.py") "${Host_}:${RemoteDir}/app/"
scp -i $SshKey (Join-Path $TryonLocal "static\*") "${Host_}:${RemoteDir}/static/"
scp -i $SshKey (Join-Path $TryonLocal "deploy\soco-tryon.service") "${Host_}:${RemoteDir}/deploy/"

$localEnv = Join-Path $TryonLocal ".env"
if (Test-Path $localEnv) {
    Write-Host "==> Upload .env" -ForegroundColor Cyan
    scp -i $SshKey $localEnv "${Host_}:${RemoteDir}/.env"
    ssh -i $SshKey $Host_ "chmod 600 $RemoteDir/.env"
} else {
    Write-Host "==> No local tryon-web\.env — will create from example on server" -ForegroundColor Yellow
    ssh -i $SshKey $Host_ @"
if [ ! -f $RemoteDir/.env ]; then
  cp $RemoteDir/.env.example $RemoteDir/.env
  chmod 600 $RemoteDir/.env
fi
"@
}

Write-Host "==> Install venv + systemd" -ForegroundColor Cyan
ssh -i $SshKey $Host_ @"
set -e
cd $RemoteDir
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
sed -i 's/\r$//' deploy/soco-tryon.service
cp deploy/soco-tryon.service /etc/systemd/system/soco-tryon.service
systemctl daemon-reload
systemctl enable soco-tryon
systemctl restart soco-tryon
sleep 2
systemctl --no-pager --full status soco-tryon | head -n 20
curl -s http://127.0.0.1:$Port/api/health || true
echo
# open firewall if ufw active
if command -v ufw >/dev/null 2>&1; then
  ufw allow $Port/tcp || true
fi
"@

Write-Host "`n[DONE] Try-on site: http://${VpsIp}:$Port" -ForegroundColor Green
Write-Host "Health: http://${VpsIp}:$Port/api/health"
Write-Host "If perfectcorp_configured=false — put PERFECTCORP_API_KEY into $RemoteDir/.env and restart: systemctl restart soco-tryon"
