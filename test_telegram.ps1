# Send a short test message via Telegram bot (.env)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-DotEnv {
    param([string]$Path)
    $vars = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
        $k, $v = $line.Split("=", 2)
        $vars[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
    }
    return $vars
}

$envVars = Get-DotEnv ".env"
$token = $envVars["TELEGRAM_BOT_TOKEN"]
$chatId = $envVars["TELEGRAM_CHAT_ID"]
if (-not $token -or -not $chatId) { throw "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env" }

$text = "Тест Mango pipeline: Telegram работает. $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$uri = "https://api.telegram.org/bot$token/sendMessage"
$resp = Invoke-RestMethod -Uri $uri -Method Post -Body @{
    chat_id = $chatId
    text    = $text
}
if ($resp.ok) {
    Write-Host "[OK] Message sent to chat $chatId"
} else {
    Write-Host "[FAIL]" ($resp | ConvertTo-Json)
    exit 1
}
