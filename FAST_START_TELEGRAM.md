# Быстрый запуск на следующий раз

Скрипт: `process_calls_to_telegram.ps1`

## 1) Куда положить звонки
- Скопируйте новые `*.html` звонков в папку `mangocursor`.

## 2) Запуск в 1 команду (автоотбор + docx + отправка)
```powershell
powershell -ExecutionPolicy Bypass -File .\process_calls_to_telegram.ps1 `
  -BaseDir "." `
  -SelectionFile "selected_calls.json" `
  -AutoSelect `
  -SendDocx `
  -BotToken "ВАШ_BOT_TOKEN" `
  -ChatId "ВАШ_CHAT_ID"
```

## 3) Что делает скрипт
- Автоматически выбирает проблемные звонки по ключевым словам.
- Пишет итоговый список в `selected_calls.json`.
- Делает расшифровки в `telegram_exports\call_XX.txt`.
- Конвертирует в `telegram_docx\call_XX.docx`.
- Отправляет все `docx` в Telegram.

## 4) Проверка без отправки (только подготовка файлов)
```powershell
powershell -ExecutionPolicy Bypass -File .\process_calls_to_telegram.ps1 `
  -BaseDir "." `
  -SelectionFile "selected_calls.json" `
  -AutoSelect `
  -SendDocx `
  -DryRun
```

## 5) Ручной список вместо автоотбора
- Отредактируйте `selected_calls.json` вручную.
- Запускайте **без** `-AutoSelect`.

## Важно
- Для `docx` нужен установленный Microsoft Word (у вас есть).
- На iPhone Telegram `docx` открывается лучше, чем `txt`.
