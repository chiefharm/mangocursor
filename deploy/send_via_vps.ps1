# Отправка отчёта в Telegram только через VPS
param(
    [string]$Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd"),
    [string]$VpsIp,
    [int]$MaxAttempts = 20,
    [int]$DelaySec = 30
)

$ErrorActionPreference = "Continue"
$Key = "$env:USERPROFILE\.ssh\id_ed25519"
$Root = Split-Path $PSScriptRoot -Parent
$hostFile = Join-Path $PSScriptRoot "vps.host"
if (-not $VpsIp -and (Test-Path $hostFile)) {
    $VpsIp = (Get-Content $hostFile -Raw).Trim()
}
if (-not $VpsIp) { $VpsIp = "YOUR_VPS_IP" }

$Host_ = "root@$VpsIp"
$Remote = "/opt/mango-pipeline"

$files = @(
    "call_qc.py", "send_day_to_telegram.py", "transcript_utils.py",
    "mango_vpbx.py", "yandex_stt.py", "telegram_format.py"
) | ForEach-Object { Join-Path $Root $_ }

$html = Get-ChildItem (Join-Path $Root "$Date__*.html") -ErrorAction SilentlyContinue

for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Host "[$i/$MaxAttempts] SSH -> $Host_ ..."
    $test = ssh -i $Key -o ConnectTimeout=20 -o BatchMode=yes $Host_ "echo SSH_OK" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  fail: $test"
        Start-Sleep -Seconds $DelaySec
        continue
    }
    Write-Host "  connected, syncing..."
    scp -i $Key @files "${Host_}:${Remote}/"
    if ($html) { scp -i $Key @($html.FullName) "${Host_}:${Remote}/" }
    ssh -i $Key $Host_ "/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/send_day_to_telegram.py --date $Date --base-dir /opt/mango-pipeline"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[DONE] Sent via VPS $VpsIp for $Date"
        exit 0
    }
    Start-Sleep -Seconds $DelaySec
}
Write-Host "[FAIL] VPS $VpsIp unreachable after $MaxAttempts attempts"
exit 1
