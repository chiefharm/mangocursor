# SOCO AI Try-On (YouCam / Perfect Corp)

Отдельный сайт для AI-примерки стрижек/окрашивания.

## Что умеет

1. Фото «до» — загрузка файла или съёмка с камеры
2. До **3** референсов из портфолио
3. Результат «после» — по одному варианту на каждый референс

## Локальный запуск

```bash
cd tryon-web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# впишите PERFECTCORP_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8088 --reload
```

Откройте: http://127.0.0.1:8088

## Деплой на VPS

```bash
# на сервере
sudo mkdir -p /opt/soco-tryon
# скопируйте содержимое tryon-web/ в /opt/soco-tryon/
cd /opt/soco-tryon
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # PERFECTCORP_API_KEY

sudo cp deploy/soco-tryon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now soco-tryon
```

Nginx (опционально):

```nginx
server {
  listen 80;
  server_name tryon.soco-salon.ru;  # или IP

  client_max_body_size 20m;

  location / {
    proxy_pass http://127.0.0.1:8088;
    proxy_read_timeout 300s;
  }
}
```

## Важно

- API-ключ Perfect Corp **только** в `.env` на сервере, не в git
- Результаты — AI-превью, не гарантия итоговой стрижки
- Фото клиентов хранятся временно в `data/uploads` и `data/results`
