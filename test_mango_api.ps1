# Test Mango VPBX API connection (reads .env in project root)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-DotEnv {
    param([string]$Path)
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
        $k, $v = $line.Split("=", 2)
        $vars[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
    }
    return $vars
}

$envVars = Get-DotEnv ".env"
$apiKey = $envVars["MANGO_VPBX_API_KEY"]
$apiSalt = $envVars["MANGO_VPBX_API_SALT"]

if (-not $apiKey -or -not $apiSalt -or $apiKey -match "replace") {
    Write-Host "[SKIP] Add MANGO_VPBX_API_KEY and MANGO_VPBX_API_SALT to .env (API connector in Mango LK)"
    exit 1
}

# Moscow UTC+3 (no DST since 2014)
$day = (Get-Date).AddDays(-1).Date
$startUnix = [int][double]([DateTimeOffset]::new($day.AddHours(3).ToUniversalTime())).ToUnixTimeSeconds()
$endUnix = $startUnix + 86400 - 1

$payload = (@{
    date_from = [string]$startUnix
    date_to   = [string]$endUnix
    fields    = "records,start,finish,answer,from_number,to_number,entry_id"
} | ConvertTo-Json -Compress)

$signBytes = [Text.Encoding]::UTF8.GetBytes("$apiKey$payload$apiSalt")
$sha = [System.Security.Cryptography.SHA256]::Create()
$sign = -join ($sha.ComputeHash($signBytes) | ForEach-Object { $_.ToString("x2") })

$body = @{
    vpbx_api_key = $apiKey
    sign         = $sign
    json         = $payload
}

Write-Host "[TEST] Mango stats/request for $($day.ToString('yyyy-MM-dd')) ..."
$resp = Invoke-RestMethod -Uri "https://app.mango-office.ru/vpbx/stats/request" -Method Post -Body $body
if (-not $resp.key) {
    Write-Host "[FAIL] stats/request:" ($resp | ConvertTo-Json -Compress)
    exit 1
}
Write-Host "[OK] stats/request key received, polling result ..."

$resultPayload = (@{ key = $resp.key } | ConvertTo-Json -Compress)
$sign2 = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes("$apiKey$resultPayload$apiSalt")) | ForEach-Object { $_.ToString("x2") })
$resultBody = @{
    vpbx_api_key = $apiKey
    sign         = $sign2
    json         = $resultPayload
}

for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 2
    $raw = Invoke-WebRequest -Uri "https://app.mango-office.ru/vpbx/stats/result" -Method Post -Body $resultBody -UseBasicParsing
    $text = $raw.Content
    if ($text -and $text -notmatch '"status"\s*:\s*"work"') {
        $lines = ($text -split "`n" | Where-Object { $_.Trim() })
        $count = [Math]::Max(0, $lines.Count - 1)
        Write-Host "[OK] Got call history: $count calls for yesterday"
        if ($count -gt 0) {
            Write-Host ($lines | Select-Object -First 3)
        }
        exit 0
    }
    Write-Host "  attempt $i/15 - still processing..."
}

Write-Host "[FAIL] Timed out waiting for stats/result"
exit 1
