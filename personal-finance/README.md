# Касса — личные финансы

Отдельный сервис. **Не связан** с салоном, Mango, QC-звонками и рабочими Telegram-группами.

Сайт, куда загружается выписка из банка. Статьи расходов берутся из файла (как их подписал банк). Переводы между счетами обычно **без кода статьи** — их нужно пояснить в интерфейсе: куда ушли деньги, или это движение между своими счетами.

После загрузки (и когда очередь переводов разобрана) можно получить сводку в Telegram — в личку, отдельным ботом.

## Что делает

1. Загрузка CSV / Excel (Тинькофф, Сбер, Альфа и любой файл с колонками дата + сумма + категория).
2. Доходы и расходы по **банковским** рубрикам.
3. Очередь «нужно пояснить» для переводов без статьи.
4. Сводка за месяц и сравнение с прошлым.
5. Сообщение в Telegram после импорта.

Переводы, помеченные «между своими», в доходы/расходы **не входят**.

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
git -C /opt/mango-pipeline fetch origin cursor/personal-finance-web-2b09 && \
git -C /opt/mango-pipeline show origin/cursor/personal-finance-web-2b09:personal-finance/deploy/install_on_vps.sh | bash
```

Скрипт поставит systemd (`personal-finance` + `personal-finance-bot`), откроет порт 8090, создаст пароль входа. Токен бота может взять из mango `.env`, **чат — замените на id группы кассы** (отрицательный). Группы SOCO не использовать.

Сайт: `http://ВАШ_IP:8090`

## Telegram-группа

1. Создайте отдельную группу (не салон).
2. Добавьте бота, в `.env` пропишите `FINANCE_TELEGRAM_CHAT_ID` группы.
3. На сайте задайте цель месяца **или** в группе: `/цель 80000`.
4. После загрузки выписки: если есть переводы без статьи — короткое «разнесите на сайте». Когда очередь пустая — итоги, всплески, советы и кнопки: норма / сократить / не расход.

Слушатель кнопок: `systemctl status personal-finance-bot`. Один бот не должен крутить `getUpdates` в другом процессе.

Nginx (пример):

```nginx
server {
  listen 80;
  server_name money.example.com;
  client_max_body_size 16m;
  location / {
    proxy_pass http://127.0.0.1:8090;
  }
}
```

## Секреты

Только в `.env`, не в git:

- `FINANCE_PASSWORD` — вход на сайт
- `FINANCE_TELEGRAM_BOT_TOKEN` / `FINANCE_TELEGRAM_CHAT_ID` — **группа кассы**, не чаты салона
- `FINANCE_SITE_URL` — ссылка на сайт в сообщении «разнесите переводы»

База: `data/ledger.sqlite` (выписки и пояснения).
