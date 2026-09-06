# Copy «Касса» to the European VPS (same deploy/vps.host as mango).
#   .\personal-finance\deploy\deploy_to_vps.ps1
param(
    [string]$VpsIp,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RemoteDir = "/opt/personal-finance",
    [int]$Port = 8090,
    [string]$Domain = "kassa.rost-i-razvitie.ru"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $Root "personal-finance\app\main.py"))) {
    $Root = Split-Path $PSScriptRoot -Parent
}
$App = Join-Path $Root "personal-finance"
$hostFile = Join-Path $Root "deploy\vps.host"

if (-not $VpsIp -and (Test-Path $hostFile)) {
    $VpsIp = (Get-Content $hostFile -Raw).Trim()
}
if (-not $VpsIp) { throw "Укажите -VpsIp или создайте deploy\vps.host" }
if (-not (Test-Path $SshKey)) { throw "SSH-ключ не найден: $SshKey" }

$Host_ = "root@$VpsIp"
Write-Host "==> SSH $Host_" -ForegroundColor Cyan
ssh -i $SshKey -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new $Host_ "echo SSH_OK && uname -a"

Write-Host "==> upload $RemoteDir" -ForegroundColor Cyan
ssh -i $SshKey $Host_ "mkdir -p $RemoteDir/app $RemoteDir/static $RemoteDir/deploy $RemoteDir/data/uploads"
scp -i $SshKey `
    (Join-Path $App "requirements.txt") `
    (Join-Path $App "README.md") `
    (Join-Path $App ".env.example") `
    (Join-Path $App "pytest.ini") `
    "${Host_}:${RemoteDir}/"
scp -i $SshKey (Join-Path $App "app\*.py") "${Host_}:${RemoteDir}/app/"
scp -i $SshKey (Join-Path $App "static\*") "${Host_}:${RemoteDir}/static/"
scp -i $SshKey (Join-Path $App "deploy\*") "${Host_}:${RemoteDir}/deploy/"

Write-Host "==> install" -ForegroundColor Cyan
ssh -i $SshKey $Host_ "chmod +x $RemoteDir/deploy/*.sh; sed -i 's/\r`$//' $RemoteDir/deploy/*.sh $RemoteDir/deploy/*.service; FINANCE_SKIP_FETCH=1 DEST=$RemoteDir FINANCE_PORT=$Port FINANCE_DOMAIN=$Domain bash $RemoteDir/deploy/install_on_vps.sh"

Write-Host "Касса: https://$Domain  (A-запись kassa → $VpsIp)"
Write-Host "Пока DNS не обновился: http://${VpsIp}:$Port"
