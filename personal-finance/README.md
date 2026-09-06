# Касса — личные финансы

Отдельный сервис. **Не связан** с салоном, Mango, QC-звонками и рабочими Telegram-группами.

## Когда будете за компьютером

Одна команда с ПК (нужны `deploy/vps.host` и SSH-ключ, как для mango):

```powershell
.\personal-finance\deploy\deploy_to_vps.ps1
```

Скрипт поставит сайт на `http://IP:8090`, возьмёт токен `@chiefharmcursorbot` с VPS и сам найдёт группу **«учет финансов»**. В группу уйдёт сообщение «Касса подключена».

Если бот группу ещё не видит — напишите там любое слово и на сервере:

```bash
cd /opt/personal-finance
.venv/bin/python -m app.chats --bind "учет финансов" --notify
systemctl restart personal-finance personal-finance-bot
```

Дальше с iPhone: открыть сайт, задать цель, загрузить выписку, разнести переводы без статьи. Отчёты и кнопки — в этой группе.

## Что делает

1. Загрузка PDF / CSV / Excel (Альфа, Тинькофф, Сбер) или кнопка **«Забрать с Google Drive»**.
2. Статьи расходов как в банке (у PDF Альфа — по MCC).
3. Очередь «куда ушли деньги» для переводов без статьи. Копилка и переводы между своими счетами сами помечаются «между своими».
4. Цель месяца (сальдо) на сайте или `/цель 80000`.
5. В группу: итоги, всплески, как дотянуть цель, кнопки норма / сократить / не расход.

Переводы «между своими» в доходы/расходы не входят. **Имя файла не важно** — период берётся из дат операций внутри выписки, повторно одни и те же строки не задвоятся.

Папка с выписками: https://drive.google.com/drive/folders/1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj  
С сервера: `python -m app.pull` (или `--dry-run` только посмотреть).

## Локальный запуск

```bash
cd personal-finance
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# впишите FINANCE_PASSWORD и, по желанию, Telegram
uvicorn app.main:app --host 127.0.0.1 --port 8090 --reload
```

Откройте http://127.0.0.1:8090

Тесты:

```bash
cd personal-finance
PYTHONPATH=. python -m pytest -q
```

## Деплой на европейский VPS (свой каталог, не mango-pipeline)

Путь на сервере: `/opt/personal-finance`, порт **8090**. Салонный пайплайн не трогаем.

С компьютера, где уже есть `deploy/vps.host` и SSH-ключ:

```powershell
.\personal-finance\deploy\deploy_to_vps.ps1
```

или:

```bash
bash personal-finance/deploy/deploy_to_vps.sh
```

С консоли Timeweb (без ПК) — одна команда, файлы берутся из уже клонированного `/opt/mango-pipeline`:

```bash
git -C /opt/mango-pipeline fetch origin cursor/kassa-domain-2b09 && \
FINANCE_GIT_BRANCH=cursor/kassa-domain-2b09 \
FINANCE_DOMAIN=kassa.rost-i-razvitie.ru \
git -C /opt/mango-pipeline show origin/cursor/kassa-domain-2b09:personal-finance/deploy/install_on_vps.sh | bash
```

Скрипт ставит systemd, nginx и (если DNS уже смотрит на VPS) сертификат Let's Encrypt. Группы SOCO не трогает.

## Домен

На **rost-i-razvitie.ru** уже сайт психологического центра (хостинг Vigbo). Его не трогаем.

Касса: **https://kassa.rost-i-razvitie.ru**

В DNS Vigbo добавьте одну запись и **не меняйте** NS / A корня:

| Имя | Тип | Значение |
|-----|-----|----------|
| `kassa` | A | IP европейского VPS (Timeweb) |

Потом на сервере:

```bash
FINANCE_DOMAIN=kassa.rost-i-razvitie.ru bash /opt/personal-finance/deploy/setup_domain.sh
```

## Telegram-группа

Группа «учет финансов» + `@chiefharmcursorbot` уже задуманы. Привязку id делает `python -m app.chats --bind "учет финансов"`. Не использовать чаты салона.

Слушатель кнопок: `systemctl status personal-finance-bot`. На этом токене `getUpdates` крутит только касса, не mango.

Nginx ставит `deploy/setup_domain.sh`. Пример: `deploy/kassa.nginx.example`.

## Секреты

Только в `.env`, не в git:

- `FINANCE_PASSWORD` — вход на сайт
- `FINANCE_TELEGRAM_BOT_TOKEN` / `FINANCE_TELEGRAM_CHAT_ID` — **группа кассы**, не чаты салона
- `FINANCE_SITE_URL` — ссылка на сайт в сообщении «разнесите переводы»
- `FINANCE_DOMAIN` — `kassa.rost-i-razvitie.ru` (корень домена не занимаем)
- `FINANCE_DRIVE_FOLDER` — папка Google Drive с выписками (ссылка уже в `.env.example`)

База: `data/ledger.sqlite` (выписки и пояснения).
