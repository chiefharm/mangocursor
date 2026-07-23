# Run all local tests for Mango pipeline
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
}

Write-Host "========== 1. Mango API =========="
powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\test_mango_api.ps1"
$mangoOk = $LASTEXITCODE -eq 0

Write-Host "`n========== 2. Telegram =========="
powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\test_telegram.ps1"
$tgOk = $LASTEXITCODE -eq 0

if (Test-Path $py) {
    Write-Host "`n========== 3. Mango sync =========="
    & $py mango_sync.py --days 1

    Write-Host "`n========== 4. Pipeline dry-run =========="
    & $py daily_pipeline.py --dry-run
} else {
    Write-Host "[SKIP] Python not found for mango_sync / daily_pipeline"
}

Write-Host "`n========== SUMMARY =========="
Write-Host ("Mango API: {0}" -f ($(if ($mangoOk) { "OK" } else { "FAIL" })))
Write-Host ("Telegram:  {0}" -f ($(if ($tgOk) { "OK" } else { "FAIL (api.telegram.org blocked without VPN)" })))
