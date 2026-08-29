# Perfect Corp / YouCam — краткая справка (AI-примерка причёски)

> Для AI: читать перед правками `tryon-web/`. Источник: [docs intro](https://docs.perfectcorp.com/develop/introduction), [ai_hairstyle](https://docs.perfectcorp.com/reference/ai_hairstyle), live `GET /s2s/v2.0/credit/feature-cost` (01.08.2026).

## Что используем

| | |
|--|--|
| Продукт | **AI Hair Style Virtual Try-On V2.1** — custom reference (`hair-transfer`) |
| Base | `https://yce-api-01.makeupar.com` |
| Auth | `Authorization: Bearer <PERFECTCORP_API_KEY>` |
| File API | `POST /s2s/v2.1/file/hair-transfer` → `file_id` + PUT URL |
| Task | `POST /s2s/v2.1/task/hair-transfer` (`src_file_id` + `ref_file_id` / URL / `template_id`) |
| Poll | `GET /s2s/v2.1/task/hair-transfer/{task_id}` каждые ~3с, не бросать polling |
| Код | `tryon-web/app/perfectcorp.py`, UI `tryon-web/static/` |

Альтернативы референса: свой файл (`ref_file_id` / `ref_file_url`) **или** пресет (`template_id` из `/s2s/v2.1/task/template/hair-transfer`). Для SOCO нужен **свой** референс из портфолио/клиента.

## Цена (units = «токены» API)

| SKU | Endpoint | Units / результат |
|-----|----------|-------------------|
| **V2 Custom / Preset hair-transfer** | `/s2s/v2.1/task/hair-transfer` | **2.00** |
| V1 template-only `hair-style` | `/s2s/v2.0/task/hair-style` | **1.00** (только пресеты, без своего фото-стиля) |
| Hair Color | `/s2s/v2.0/task/hair-color` | 1.00 |

- Списание: **за успешный `result_image`**, не за размер файла и не за upload.
- Upload File API — **бесплатно**.
- Ошибка движка (`task_status=error`) — units обычно **не** списывают.
- Обрыв polling / timeout задачи — units **могут** списать даже если результат «потеряли».
- Баланс: `GET /s2s/v1.0/client/credit`; прайс: `GET /s2s/v2.0/credit/feature-cost`.

**Вывод по экономии:** уменьшить JPEG / сторону &lt;1024 **не удешевит** примерку. 2 units — фикс SKU для custom transfer. Дешевле 2 только другой продукт (V1 пресеты = 1), который **не** подходит под «фото работы SOCO».

Сессия UI: 1 селфи + N рефов = **N × 2** units (у нас max 3 → до **6**). Селфи один раз upload + один `src_file_id` на все рефы — правильно.

## Требования к фото (hair-transfer)

| Параметр | Лимит |
|----------|--------|
| Формат | **jpg/jpeg** только |
| Размер файла | &lt; 10 MB |
| Длинная сторона | **≤ 1024** |
| Лицо | одно, анфас; face width ≥ 128 |
| Поза | pitch ±10°, yaw ±45°, roll ±15° |
| Типичные ошибки | `error_no_shoulder`, `error_face_pose`, `error_large_face_angle`, `error_hair_too_short` |

У нас уже: клиент + сервер даунскейл до **1024** JPEG (`app.js` / `watermark.py`). Ниже 1024 — только экономия RAM/трафика VPS, не units.

## Наш пайплайн — чеклист

1. ✅ Bearer API key только на сервере (`.env`)
2. ✅ File API v2.1 `hair-transfer` + PUT
3. ✅ Task v2.1 `src_file_id` + `ref_file_id`
4. ✅ Poll до success/error
5. ✅ Парсинг `results.url` (объект, не массив строк)
6. ✅ Даунскейл ≤1024, mirror селфи, watermark `@soco.salon`
7. ✅ Очередь `TRYON_MAX_CONCURRENT=1` на 2GB VPS
8. ⚠️ Каждый реф = отдельный платный task (ожидаемо)
9. ⚠️ V1 `hair-style` за 1 unit — не использовать для портфолио-рефов

## Как не жечь units зря

- Не запускать try-on без валидного лица (лучше UX-подсказка до API).
- Не слать 3 рефа «на всякий» — default 1, остальные опционально.
- Не ретраить success-задачи; при fail без URL — можно retry один раз.
- Держать polling до конца (иначе риск списания без картинки).
- Публичные `ref_file_url` портфолио на CDN — можно без повторного upload рефа.

## Полезные ссылки

- Intro: https://docs.perfectcorp.com/develop/introduction  
- Hairstyle API: https://docs.perfectcorp.com/reference/ai_hairstyle  
- Pricing UI: https://yce.perfectcorp.com/ai-api/api-pricing  
- Console / keys: https://yce.makeupar.com/api-console/en/api-keys/  
- Playground: https://yce.makeupar.com/api-console/en/api-playground/ai-hair-style-generator/  

*Обновлено: 2026-08-01*
