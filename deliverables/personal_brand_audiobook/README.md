# How to Build a Personal Brand — Audiobook

Личная расшифровка и сборка аудиокниги из YouTube-курса Caleb Ralston:

**https://youtu.be/Ch4Sl0POBhU** (~6 ч 19 мин оригинала → **6 ч 27 мин** озвучки)

## Состав (в репо)

| Файл | Описание |
|------|----------|
| `How_to_Build_a_Personal_Brand_AUDIOBOOK.docx` | Книга по 32 главам (удобно на iPhone) |
| `AUDIOBOOK_MANUSCRIPT.md` | Та же рукопись в Markdown |
| `full_transcript.txt` | Сырая сплошная расшифровка (~73k слов) |
| `chapters/*.txt` | Текст по главам |
| `generate_tts.py` | Пересборка озвучки (edge-tts, голос Andrew) |

## Аудио (артефакты агента, не в git)

Путь: `/opt/cursor/artifacts/personal_brand_audiobook/`

| Файл | Размер | Описание |
|------|--------|----------|
| `How_to_Build_a_Personal_Brand_AUDIOBOOK.mp3` | ~134 MB | Полная аудиокнига |
| `How_to_Build_a_Personal_Brand_AUDIOBOOK_lite.mp3` | ~89 MB | Mono 32 kbps, легче качать |
| `chapters_mp3/*.mp3` | — | Те же главы по отдельности |
| `How_to_Build_a_Personal_Brand_AUDIOBOOK.docx` | — | Копия DOCX |

## Как пересобрать аудио

```bash
cd deliverables/personal_brand_audiobook
python3 generate_tts.py          # все главы + полный MP3
python3 generate_tts.py 00 01    # только выбранные
```

> Оригинальный звук с YouTube с cloud IP недоступен (бот-проверка), поэтому озвучка синтетическая по расшифровке. Авторские права на контент — у правообладателя курса; это личная копия для удобства.


## Русская версия

- `chapters_ru/*.txt` — машинный перевод EN→RU
- `How_to_Build_a_Personal_Brand_AUDIOBOOK_RU.docx` — рукопись
- `generate_tts_ru.py` / `translate_ru.py` — пайплайн
- Аудио (артефакты): `How_to_Build_a_Personal_Brand_AUDIOBOOK_RU.mp3` (~8 ч 25 мин, голос Dmitry)
