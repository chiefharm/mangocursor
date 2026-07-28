# Автоматическая отправка расшифровок с VPS

Пайплайн работает 24/7 на VPS и каждый день в **10:00 МСК**:
1. Забирает звонки из Mango API
2. Расшифровывает через Yandex SpeechKit
3. Фильтрует косячные (`call_qc.py`)
4. Отправляет в Telegram: сводка + комментарий + DOCX

## Новый сервер (миграция)

### 1. Создать VPS в Timeweb

- **ОС:** Ubuntu 24.04
- **Регион:** Европа, но **не Qupra NL** (там был инцидент с кондиционированием)
- **SSH-ключ** при создании — содержимое файла:
  ```
  %USERPROFILE%\.ssh\id_ed25519.pub
  ```
  (комментарий `chief-vps`)

### 2. Установить всё одной командой (с Windows)

```powershell
cd C:\Users\chief\Desktop\cursor\mangocursor
.\deploy\setup_new_vps.ps1 -VpsIp НОВЫЙ_IP
```

С Hermes-ботом (cursor-tg):
```powershell
.\deploy\setup_new_vps.ps1 -VpsIp НОВЫЙ_IP -InstallHermes
```

Скрипт сам:
- ставит mango-pipeline (`vps_install.sh`)
- копирует `.env` и все Python-скрипты
- копирует расшифровки 25.06 (если есть локально)
- проверяет Telegram API
- отправляет тестовый отчёт за 25.06
- сохраняет IP в `deploy/vps.host`

### 3. Ручная установка (если нужно)

```bash
ssh root@НОВЫЙ_IP
curl -fsSL https://raw.githubusercontent.com/chiefharm/mangocursor/master/deploy/vps_install.sh -o /root/vps_install.sh
bash /root/vps_install.sh
nano /opt/mango-pipeline/.env
```

## Ежедневная работа

Отправить отчёт за день (только через VPS):
```powershell
.\deploy\send_via_vps.ps1 -Date 2026-06-25
```

Синхронизировать код:
```powershell
.\deploy\sync_to_vps.ps1
```

На сервере:
```bash
systemctl status mango-pipeline.timer
journalctl -u mango-pipeline.service -n 50
```

## Секреты в `.env`

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
MANGO_VPBX_API_KEY=...
MANGO_VPBX_API_SALT=...
YANDEX_STT_ENABLED=1
YANDEX_SPEECHKIT_API_KEY=...
YANDEX_FOLDER_ID=...
```

## Старые серверы (не использовать)

IP старых VPS **не храним в git** — только актуальный в `deploy/vps.host` (локально).
