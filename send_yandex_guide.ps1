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

$text = @"
Yandex SpeechKit — как получить API-ключ

1) console.yandex.cloud — войти
2) Создать каталог (folder) или выбрать существующий
3) Сервисы → SpeechKit → включить
4) IAM → Сервисные аккаунты → Создать
5) Роль: ai.speechkit-stt.user
6) Создать API-ключ для аккаунта
7) В .env проекта mangocursor:

YANDEX_STT_ENABLED=1
YANDEX_SPEECHKIT_API_KEY=вставить_ключ
YANDEX_FOLDER_ID=id_каталога (b1g...)

Тест:
python mango_sync.py --days 1 --yandex

Подробно: YANDEX_STT_SETUP.md в проекте
"@

$uri = "https://api.telegram.org/bot$token/sendMessage"
$resp = Invoke-RestMethod -Uri $uri -Method Post -Body @{ chat_id = $chatId; text = $text }
if ($resp.ok) { Write-Host "[OK] Sent to Telegram" } else { Write-Host "[FAIL]"; exit 1 }
