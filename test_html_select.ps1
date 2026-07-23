# Count problematic calls in local HTML transcripts (same patterns as daily_pipeline.py)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$patterns = @(
    @{ Regex = "невозможно записаться|ошибка|не да[её]т|техподдерж|сбой"; Category = "Техсбой/онлайн-запись" }
    @{ Regex = "сколько стоит|стоимость|цена|дорого"; Category = "Цена/риск потери" }
    @{ Regex = "перезвоню|подумаю|пока просто отменим|не смогу"; Category = "Не закрыт в запись" }
    @{ Regex = "отменить запись|перезаписаться|перенести|перенос"; Category = "Перенос/отмена" }
    @{ Regex = "не устраивает|позднее время|пораньше|попозже"; Category = "Неудобное время" }
    @{ Regex = "недовол|жалоб|претенз|извин"; Category = "Недовольство/жалоба" }
    @{ Regex = "первый раз|ранее были"; Category = "Новый клиент" }
    @{ Regex = "не делаем|отказ"; Category = "Отказ в услуге" }
)

$files = Get-ChildItem -Filter "*.html" | Where-Object { $_.Name -ne "index.html" }
$selected = @()
foreach ($file in $files) {
    $raw = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)
    foreach ($p in $patterns) {
        if ($raw -match $p.Regex) {
            $selected += [PSCustomObject]@{ File = $file.Name; Category = $p.Category }
            break
        }
    }
}

Write-Host "[INFO] HTML files: $($files.Count)"
Write-Host "[INFO] Problematic (auto-select): $($selected.Count)"
$selected | Group-Object Category | Sort-Object Count -Descending | ForEach-Object {
    Write-Host ("  {0}: {1}" -f $_.Name, $_.Count)
}
if ($selected.Count -gt 0) {
    Write-Host ""
    Write-Host "Examples:"
    $selected | Select-Object -First 5 | ForEach-Object { Write-Host ("  - {0} [{1}]" -f $_.File, $_.Category) }
}
