# Синхронизация кода на VPS (читает IP из deploy/vps.host)
param(
    [string]$VpsIp,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519"
)

$Root = Split-Path $PSScriptRoot -Parent
$hostFile = Join-Path $PSScriptRoot "vps.host"
if (-not $VpsIp -and (Test-Path $hostFile)) {
    $VpsIp = (Get-Content $hostFile -Raw).Trim()
}
if (-not $VpsIp) {
    throw "Укажите -VpsIp или создайте deploy/vps.host"
}

$Host_ = "root@$VpsIp"
$Remote = "/opt/mango-pipeline"
$files = @(
    "call_qc.py", "daily_pipeline.py", "mango_sync.py", "mango_vpbx.py",
    "send_day_to_telegram.py", "transcript_utils.py", "yandex_stt.py",
    "site_config.py", "telegram_notify.py", "telegram_format.py",
    "get_telegram_chat_ids.py", "revenue_report.py", "tryon_usage_report.py",
    "requirements.txt",
    "PROJECT_MEMORY.md", "SESSION_LOG.md", "CODE_MAP.md", "AGENTS.md"
) | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path $_ }

ssh -i $SshKey $Host_ "mkdir -p $Remote/deploy $Remote/logs"
scp -i $SshKey @files "${Host_}:${Remote}/"
$deployFiles = @(
    (Join-Path $Root "deploy\install_revenue_cron.sh"),
    (Join-Path $Root "deploy\install_tryon_usage_cron.sh"),
    (Join-Path $Root "deploy\vps_install.sh")
) | Where-Object { Test-Path $_ }
if ($deployFiles.Count -gt 0) {
    scp -i $SshKey @deployFiles "${Host_}:${Remote}/deploy/"
}
Write-Host "[OK] synced to $VpsIp"
