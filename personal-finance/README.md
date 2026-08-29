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

## Деплой (свой каталог, не mango-pipeline)

```bash
sudo mkdir -p /opt/personal-finance
# скопируйте содержимое personal-finance/ в /opt/personal-finance/
cd /opt/personal-finance
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env

sudo cp deploy/personal-finance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now personal-finance
```

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
- `FINANCE_TELEGRAM_BOT_TOKEN` / `FINANCE_TELEGRAM_CHAT_ID` — личный дайджест

База: `data/ledger.sqlite` (выписки и пояснения).
