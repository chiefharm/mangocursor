# How to Build a Personal Brand — Audiobook

Личная расшифровка и сборка аудиокниги из YouTube-курса Caleb Ralston:

**https://youtu.be/Ch4Sl0POBhU**

## Состав

| Файл | Описание |
|------|----------|
| `How_to_Build_a_Personal_Brand_AUDIOBOOK.docx` | Книга/рукопись по главам (удобно на iPhone) |
| `AUDIOBOOK_MANUSCRIPT.md` | Та же рукопись в Markdown |
| `full_transcript.txt` | Сырая сплошная расшифровка |
| `chapters/*.txt` | Текст по главам (32 главы) |
| `audio_chapters/*.mp3` | Озвучка по главам (edge-tts, голос Andrew) |
| `How_to_Build_a_Personal_Brand_AUDIOBOOK.mp3` | Полная аудиокнига одним файлом |
| `generate_tts.py` | Скрипт пересборки озвучки |

## Как пересобрать аудио

```bash
python3 generate_tts.py          # все главы
python3 generate_tts.py 00 01    # только выбранные
```

> Оригинальный звук с YouTube с cloud IP недоступен (бот-проверка), поэтому озвучка синтетическая по расшифровке. Авторские права на контент — у правообладателя курса; это личная копия для удобства.
