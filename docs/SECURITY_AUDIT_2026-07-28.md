# Аудит безопасности — 28.07.2026

> Репозиторий должен быть **Private**. Секреты — только `/opt/mango-pipeline/.env` на VPS.

---

## Итог

| Категория | Статус |
|-----------|--------|
| API-ключи / токены | Не найдены в git |
| Расшифровки звонков (HTML) | Удалены из репо и истории |
| Telegram ID, IP VPS, ссылки Я.Диск | Убраны из git (28.07.2026) |

---

## Где хранить чувствительное (не в GitHub)

| Данные | Где |
|--------|-----|
| Telegram bot token, chat ID, group IDs | `.env` на VPS |
| Mango / Yandex API keys | `.env` на VPS |
| Ссылки Яндекс.Диск (выручка) | `REVENUE_YADISK_*` в `.env` |
| IP VPS | `deploy/vps.host` локально (см. `deploy/vps.host.example`) |

---

## Проверка VPS с ПК

```powershell
$vps = (Get-Content deploy/vps.host -Raw).Trim()
ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@$vps
```

На сервере:

```bash
test -f /opt/mango-pipeline/.env && echo OK
grep -E 'replace_with|your_' /opt/mango-pipeline/.env || echo "Ключи заполнены"
ls -la /opt/mango-pipeline/.env
```

Копирование `.env` с ПК:

```powershell
$vps = (Get-Content deploy/vps.host -Raw).Trim()
scp -i $env:USERPROFILE\.ssh\id_ed25519 .env root@${vps}:/opt/mango-pipeline/.env
ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@$vps "chmod 600 /opt/mango-pipeline/.env"
```

---

## Рекомендации

1. GitHub → Settings → **Private**
2. Не коммитить `.env`, `deploy/vps.host`, HTML-расшифровки
3. При утечке — ротация Telegram token и Mango API keys

---

*Обновлено: 2026-07-28*
