# Полная установка mango-pipeline на новый VPS Timeweb
# Использование: .\deploy\setup_new_vps.ps1 -VpsIp 185.x.x.x
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsIp,
    [switch]$InstallHermes,
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$HermesEnv = "$env:USERPROFILE\cursor-tg-deploy\.env.backup"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Remote = "/opt/mango-pipeline"
$Host_ = "root@$VpsIp"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Write-Step "Проверка SSH к $Host_"
$test = ssh -i $SshKey -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o BatchMode=yes $Host_ "echo SSH_OK && uname -a" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host @"

SSH не подключился. Перед запуском скрипта:
1. Создайте VPS Ubuntu 24.04 в Timeweb (лучше НЕ дата-центр Qupra NL — там был инцидент)
2. При создании добавьте SSH-ключ:
   $(Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" -ErrorAction SilentlyContinue)
3. Или войдите по паролю из письма Timeweb и добавьте ключ вручную:
   mkdir -p ~/.ssh && echo 'ВАШ_ПУБЛИЧНЫЙ_КЛЮЧ' >> ~/.ssh/authorized_keys

Ошибка: $test
"@
    exit 1
}
Write-Host $test

Write-Step "Установка mango-pipeline"
$install = Join-Path $PSScriptRoot "vps_install.sh"
scp -i $SshKey $install "${Host_}:/root/vps_install.sh"
ssh -i $SshKey $Host_ "sed -i 's/\r$//' /root/vps_install.sh && bash /root/vps_install.sh"

Write-Step "Копирование .env и скриптов"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[WARN] Нет $envFile — заполните секреты на сервере вручную"
} else {
    scp -i $SshKey $envFile "${Host_}:${Remote}/.env"
}

$pyFiles = @(
    "call_qc.py", "daily_pipeline.py", "mango_sync.py", "mango_vpbx.py",
    "send_day_to_telegram.py", "transcript_utils.py", "yandex_stt.py",
    "PROJECT_MEMORY.md", "AGENTS.md"
) | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path $_ }

scp -i $SshKey @pyFiles "${Host_}:${Remote}/"

$html = Get-ChildItem (Join-Path $Root "2026-06-25__*.html") -ErrorAction SilentlyContinue
if ($html) {
    Write-Step "Копирование расшифровок 25.06"
    scp -i $SshKey @($html.FullName) "${Host_}:${Remote}/"
}

if ($InstallHermes) {
    Write-Step "Установка Hermes cursor-tg"
    $hermes = Join-Path $PSScriptRoot "install_hermes_bot.sh"
    scp -i $SshKey $hermes "${Host_}:/root/install_hermes_bot.sh"
    if (Test-Path $HermesEnv) {
        scp -i $SshKey $HermesEnv "${Host_}:/opt/cursor-tg.env"
    }
    ssh -i $SshKey $Host_ "sed -i 's/\r$//' /root/install_hermes_bot.sh && bash /root/install_hermes_bot.sh"
}

Write-Step "Проверка Telegram API с сервера"
ssh -i $SshKey $Host_ @"
curl -s -o /dev/null -w 'telegram_http:%{http_code} time:%{time_total}s\n' --max-time 10 https://api.telegram.org
systemctl is-active mango-pipeline.timer
"@

Write-Step "Тестовая отправка за 25.06"
ssh -i $SshKey $Host_ "/opt/mango-pipeline/.venv/bin/python /opt/mango-pipeline/send_day_to_telegram.py --date 2026-06-25 --base-dir /opt/mango-pipeline"

Write-Step "Сохранение IP в deploy/vps.host"
Set-Content -Path (Join-Path $PSScriptRoot "vps.host") -Value $VpsIp -Encoding utf8NoBOM

Write-Host "`n[DONE] Новый VPS готов: $VpsIp" -ForegroundColor Green
Write-Host "Обновите PROJECT_MEMORY.md при смене VPS; IP сохранён только в deploy/vps.host (не коммитить)."
