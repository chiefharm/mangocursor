$ErrorActionPreference = "Stop"

param(
    [string]$BaseDir = ".",
    [string]$SelectionFile = "selected_calls.json",
    [string]$BotToken = "",
    [string]$ChatId = "",
    [switch]$AutoSelect,
    [switch]$SendDocx,
    [switch]$DryRun
)

function Resolve-FullPath([string]$p) {
    if ([IO.Path]::IsPathRooted($p)) { return $p }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location) $p))
}

function Parse-Transcript([string]$htmlPath) {
    $raw = Get-Content -Raw -Encoding UTF8 $htmlPath
    $pattern = '<tr>\s*<td><strong>(.*?)</strong></td>.*?<td style="width: 70%">(.*?)</td>\s*</tr>'
    $matches = [regex]::Matches($raw, $pattern, [Text.RegularExpressions.RegexOptions]::Singleline -bor [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $lines = @()
    foreach ($m in $matches) {
        $speaker = $m.Groups[1].Value.Trim()
        $text = $m.Groups[2].Value
        $text = [regex]::Replace($text, "<br\s*/?>", "`n", "IgnoreCase")
        $text = [regex]::Replace($text, "<.*?>", "")
        $text = [Net.WebUtility]::HtmlDecode($text)
        $text = (($text -split "`r?`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }) -join "`n"
        if ($text) { $lines += ("{0}: {1}" -f $speaker, $text) }
    }
    return $lines
}

function Get-DateTimeFromFile([string]$fileName) {
    if ($fileName -match '^(\d{4}-\d{2}-\d{2})__(\d{2}-\d{2}-\d{2})__') {
        return ("{0} {1}" -f $Matches[1], ($Matches[2] -replace '-', ':'))
    }
    return "unknown"
}

function Get-ShortComment([string]$category) {
    $c = $category.ToLowerInvariant()
    if ($c.Contains("tech") -or $c.Contains("sboy") -or $c.Contains("problem")) { return "Online booking issue, switch to manual booking fast." }
    if ($c.Contains("price")) { return "Price objection risk, push to concrete time slot." }
    if ($c.Contains("cancel") -or $c.Contains("transfer")) { return "Reschedule risk, lock new date in same call." }
    if ($c.Contains("new client")) { return "First contact, confirm next step and booking." }
    return "Quality review needed."
}

function Auto-SelectCalls([string]$dirPath, [string]$outPath) {
    $patterns = @(
        "невозможно записаться|ошибка|не да[её]т|техподдерж|сбой",
        "сколько стоит|стоимость|цена|дорого",
        "перезвоню|подумаю|пока просто отменим|не смогу",
        "отменить запись|перезаписаться|перенести|перенос",
        "не устраивает|позднее время|пораньше|попозже",
        "первый раз|ранее были"
    )
    $htmlFiles = Get-ChildItem -Path $dirPath -Filter "*.html" | Sort-Object Name
    $selected = @()
    foreach ($f in $htmlFiles) {
        $raw = Get-Content -Raw -Encoding UTF8 $f.FullName
        $category = $null
        if ($raw -match $patterns[0]) { $category = "Tech issue" }
        elseif ($raw -match $patterns[1]) { $category = "Price risk" }
        elseif ($raw -match $patterns[2]) { $category = "Not booked" }
        elseif ($raw -match $patterns[3]) { $category = "Reschedule/cancel" }
        elseif ($raw -match $patterns[4]) { $category = "Time mismatch" }
        elseif ($raw -match $patterns[5]) { $category = "New client" }
        if ($category) {
            $selected += [pscustomobject]@{ file = $f.Name; category = $category }
        }
    }
    $json = $selected | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($outPath, $json, [Text.UTF8Encoding]::new($false))
    Write-Host ("[OK] Auto-selected: {0}" -f $selected.Count)
}

function Send-Message([string]$token, [string]$chatId, [string]$text) {
    Invoke-RestMethod -Method Post -Uri ("https://api.telegram.org/bot{0}/sendMessage" -f $token) -Body @{
        chat_id = $chatId
        text = $text
        disable_web_page_preview = "true"
    } | Out-Null
}

function Send-Docx([string]$token, [string]$chatId, [string]$filePath, [string]$caption) {
    Add-Type -AssemblyName System.Net.Http
    $uri = ("https://api.telegram.org/bot{0}/sendDocument" -f $token)
    $client = New-Object System.Net.Http.HttpClient
    try {
        $content = New-Object System.Net.Http.MultipartFormDataContent
        $content.Add((New-Object System.Net.Http.StringContent($chatId)), "chat_id")
        $content.Add((New-Object System.Net.Http.StringContent($caption)), "caption")
        $bytes = [IO.File]::ReadAllBytes($filePath)
        $fileContent = New-Object System.Net.Http.ByteArrayContent -ArgumentList (, $bytes)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        $content.Add($fileContent, "document", [IO.Path]::GetFileName($filePath))
        $resp = $client.PostAsync($uri, $content).Result
        $txt = $resp.Content.ReadAsStringAsync().Result
        if (-not $resp.IsSuccessStatusCode -or $txt -notmatch '"ok":true') {
            throw ("sendDocument failed: {0}" -f $txt)
        }
    } finally {
        $client.Dispose()
    }
}

$base = Resolve-FullPath $BaseDir
$selectionPath = Join-Path $base $SelectionFile
$txtDir = Join-Path $base "telegram_exports"
$docxDir = Join-Path $base "telegram_docx"
New-Item -ItemType Directory -Force -Path $txtDir | Out-Null
New-Item -ItemType Directory -Force -Path $docxDir | Out-Null

if ($AutoSelect) { Auto-SelectCalls -dirPath $base -outPath $selectionPath }
if (-not (Test-Path $selectionPath)) { throw ("Selection file not found: {0}" -f $selectionPath) }

$items = Get-Content -Raw -Encoding UTF8 $selectionPath | ConvertFrom-Json
if (-not $items) { throw "No calls in selection file." }

$idx = 1
foreach ($item in $items) {
    $file = [string]$item.file
    $category = [string]$item.category
    $src = Join-Path $base $file
    if (-not (Test-Path $src)) { Write-Host ("[WARN] Missing: {0}" -f $file); $idx++; continue }
    $dt = Get-DateTimeFromFile $file
    $comment = Get-ShortComment $category
    $lines = Parse-Transcript $src
    if (-not $lines -or $lines.Count -eq 0) { Write-Host ("[WARN] Empty parse: {0}" -f $file); $idx++; continue }

    $outTxt = Join-Path $txtDir ("call_{0:D2}.txt" -f $idx)
    $header = @(
        ("Call {0}/{1}" -f $idx, $items.Count),
        ("File: {0}" -f $file),
        ("Datetime: {0}" -f $dt),
        ("Category: {0}" -f $category),
        ("Comment: {0}" -f $comment),
        "",
        "Transcript:",
        ""
    )
    [IO.File]::WriteAllLines($outTxt, ($header + $lines), [Text.UTF8Encoding]::new($false))
    $idx++
}
Write-Host ("[OK] TXT ready: {0}" -f $txtDir)

if ($SendDocx) {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    try {
        $txtFiles = Get-ChildItem -Path $txtDir -Filter "*.txt" | Sort-Object Name
        foreach ($f in $txtFiles) {
            $outDocx = Join-Path $docxDir (([IO.Path]::GetFileNameWithoutExtension($f.Name)) + ".docx")
            $doc = $word.Documents.Open($f.FullName)
            $wdFormatXMLDocument = 12
            $doc.SaveAs([string]$outDocx, [ref]$wdFormatXMLDocument)
            $doc.Close()
        }
    } finally {
        $word.Quit()
    }
    Write-Host ("[OK] DOCX ready: {0}" -f $docxDir)
}

if (-not $DryRun -and $BotToken -and $ChatId) {
    Send-Message -token $BotToken -chatId $ChatId -text "Start DOCX send."
    $docs = Get-ChildItem -Path $docxDir -Filter "*.docx" | Sort-Object Name
    $n = 1
    foreach ($d in $docs) {
        Send-Docx -token $BotToken -chatId $ChatId -filePath $d.FullName -caption ("DOCX {0}/{1}" -f $n, $docs.Count)
        $n++
    }
    Send-Message -token $BotToken -chatId $ChatId -text "Done DOCX send."
    Write-Host "[OK] Telegram send done."
} else {
    Write-Host "[INFO] Send skipped."
}
