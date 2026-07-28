# Аудит безопасности — 28.07.2026

> Проверка репозитория `chiefharm/mangocursor` (PUBLIC) и cloud-агентов Cursor.

---

## Итог

| Категория | Статус | Действие |
|-----------|--------|----------|
| **API-ключи / токены** | ✅ Не найдены в git | `.env` в `.gitignore`, в истории только placeholders |
| **Данные клиентов (звонки)** | 🔴 **Были на GitHub** | 56 HTML + index + selected_calls.json — **удалены из репо** |
| **Cloud-агенты (9 шт.)** | ✅ Секреты не коммитили | Ни один не заливал ключи в код |
| **VPS `.env`** | ⚠️ Не проверен | Cloud Agent **не имеет SSH-ключа** — проверить с ПК |

---

## Что было публично на GitHub (КРИТИЧНО)

### 1. Расшифровки звонков — **56 HTML-файлов**

- Имена файлов содержат **номера телефонов клиентов** (`79XXXXXXXXX`, …)
- Внутри — **полные тексты разговоров** (имена, услуги, жалобы)
- Период: апрель 2026, салон SOCO Москва

### 2. `index.html`

- Оглавление всех расшифровок с телефонами и ссылками

### 3. `selected_calls.json`

- Список отобранных звонков с номерами в именах файлов

### 4. `telegram_exports_html/` (15 файлов)

- Экспорт расшифровок для iPhone — тоже с телефонами

**Важно:** даже после удаления файлы остаются в **истории git** до force-push с очисткой истории. См. раздел «Очистка истории» ниже.

---

## Что НЕ является утечкой ключей (но видно публично)

| Данные | Где | Риск |
|--------|-----|------|
| Telegram ID Егора `YOUR_TELEGRAM_CHAT_ID` | PROJECT_MEMORY, SESSION_LOG | низкий |
| ID групп Telegram | PROJECT_MEMORY, .env.example | низкий |
| IP VPS `YOUR_VPS_IP` | AGENTS.md, PROJECT_MEMORY | средний |
| Mango account IDs | PROJECT_MEMORY | низкий |
| Публичные ссылки Яндекс.Диск (выручка) | `.env.example` | средний — Excel с выручкой |
| SIP-адрес Mango | MANGO_API_SETUP.md | низкий |

Рекомендация: сделать репозиторий **Private** или вынести `PROJECT_MEMORY.md` / `SESSION_LOG.md` в private-заметки.

---

## Cloud-агенты (все 9 на этом репо)

| Агент | Менял GitHub? | Секреты? |
|-------|---------------|----------|
| Примерка причесок (текущий) | PR #1, docs only | нет |
| Методика продвижения экспертов | нет | нет |
| Обложка заголовок психолога | нет | нет |
| Курс евро | нет | нет |
| Недостающие звонки москва | нет | нет |
| Видео монтаж | нет | нет |
| Soco новость ngs24 | нет | нет |
| Критерии семейной ипотеки | нет | нет |
| Маршрут горы аватара | нет | нет |

**Вывод:** агенты не заливали ключи. Утечка клиентских данных — из **Initial commit** (апрель 2026), до того как `.gitignore` начал работать для уже отслеживаемых файлов.

---

## API-ключи — где должны жить

**Только на VPS:** `/opt/mango-pipeline/.env`

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
MANGO_VPBX_API_KEY=...
MANGO_VPBX_API_SALT=...
SITE_KRASNOYARSK_API_KEY=...
SITE_KRASNOYARSK_API_SALT=...
YANDEX_SPEECHKIT_API_KEY=...
REVENUE_YADISK_KRAS=...
REVENUE_YADISK_MSK=...
```

**Никогда в git:** `.env`, SSH-ключи, токены ботов.

---

## Проверка VPS с вашего ПК

Cloud Agent **не может** зайти на VPS (нет SSH-ключа). Выполните **на компьютере**:

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@YOUR_VPS_IP
```

На сервере:

```bash
# 1. Файл существует?
test -f /opt/mango-pipeline/.env && echo OK || echo "НЕТ .env!"

# 2. Нет placeholder-значений?
grep -E 'replace_with|your_|123456789:' /opt/mango-pipeline/.env && echo "Есть заглушки!" || echo "Ключи заполнены"

# 3. Какие переменные заданы (без значений)?
grep -E '^[A-Z_]+=' /opt/mango-pipeline/.env | cut -d= -f1

# 4. Права доступа
ls -la /opt/mango-pipeline/.env   # должно быть -rw------- root root
```

### Если `.env` на VPS в порядке

Ничего переносить не нужно — ключи уже там. Cloud Agent их не видел и не трогал.

### Если `.env` потерян или с заглушками

С **локального ПК** (где есть рабочий `.env`):

```powershell
scp -i $env:USERPROFILE\.ssh\id_ed25519 .env root@YOUR_VPS_IP:/opt/mango-pipeline/.env
ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@YOUR_VPS_IP "chmod 600 /opt/mango-pipeline/.env"
```

### Ротация ключей (если переживаете)

Даже если ключей не было в GitHub, после публичной утечки **телефонов клиентов** рекомендуется:

1. **Telegram:** [@BotFather](https://t.me/BotFather) → `/revoke` → новый токен → обновить `.env` на VPS
2. **Mango:** ЛК → API коннектор → перевыпустить ключ+соль → `.env`
3. **Yandex SpeechKit:** console.cloud.yandex.ru → новый API key → `.env`

---

## Очистка истории git (обязательно для PUBLIC)

Удаление файлов из текущей версии **не стирает** их из старых коммитов. Для полной очистки:

```bash
pip install git-filter-repo

# Удалить все расшифровки из всей истории
git filter-repo --force \
  --path-glob '2026-*.html' --invert-paths \
  --path index.html --invert-paths \
  --path selected_calls.json --invert-paths \
  --path-glob 'telegram_exports_html/*' --invert-paths

git push origin master --force
```

⚠️ Force-push перепишет историю. Если работаете с нескольких машин — после этого сделайте `git fetch --all && git reset --hard origin/master`.

---

## Рекомендации на будущее

1. **Settings → Change visibility → Private** для `mangocursor`
2. GitHub → **Secret scanning** (бесплатно для public repos)
3. Не коммитить HTML-расшифровки — они уже в `.gitignore`
4. `deploy/vps.host` — уже в `.gitignore` (IP только в markdown)
5. Cloud Agent: не вставлять ключи в чат и не просить коммитить `.env`

---

*Аудит выполнен Cloud Agent 28.07.2026*
