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

### Домен + HTTPS (чтобы не светить :8088)

Основные сайты `soco-salon.ru` / `soco-kras.ru` живут на **другом** хостинге.
Примерку вешаем на **поддомен** этого VPS:

1. В DNS домена создайте **A-запись**: `tryon` → IP из `deploy/vps.host`
2. На VPS:

```bash
cd /opt/soco-tryon
DOMAIN=tryon.soco-salon.ru bash deploy/setup_domain.sh
```

Ссылка для клиентов: `https://tryon.soco-salon.ru` (или ваш поддомен).

Nginx-прокси: `deploy/nginx-tryon.conf`. Uvicorn слушает только `127.0.0.1:8088`.

### Устойчивость при наплыве

На 2GB VPS одновременно крутится **1** тяжёлая примерка (`TRYON_MAX_CONCURRENT=1`).
Остальные ждут в очереди до ~2 мин, иначе получают «сейчас много примерок».
Плюс: сжатие фото до 1024px, swap 2GB, `MemoryMax` в systemd.
## Важно

- API-ключ Perfect Corp **только** в `.env` на сервере, не в git
- Результаты — AI-превью, не гарантия итоговой стрижки
- Фото клиентов хранятся временно в `data/uploads` и `data/results`

## Кабинет сотрудников

- URL: `/staff`
- Авторизация: телефон + пароль (cookie-сессия)
- Генерация: сразу на сайте, **без бота** и **без месячного лимита**
- Хранение: 30 дней в `clients.sqlite3` + фото в `data/uploads|results`

Первичная выдача логина/пароля через `.env`:

```env
TRYON_STAFF_BOOTSTRAP=+79990001122:strong_password:Администратор
TRYON_STAFF_SIGNING_KEY=change_me_staff_signing_key
```
