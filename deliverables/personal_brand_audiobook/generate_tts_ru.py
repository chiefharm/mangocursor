#!/usr/bin/env python3
"""Generate Russian chapter MP3s via edge-tts, then concat full audiobook."""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent
CHAP_DIR = ROOT / "chapters_ru"
AUDIO_DIR = ROOT / "audio_chapters_ru"
VOICE = "ru-RU-DmitryNeural"
MAX_CHARS = 2500  # slightly smaller for Cyrillic
CONCURRENCY = 6


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buf = ""
    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?…])\s+", para)
        for sent in sentences:
            if not sent:
                continue
            candidate = (buf + " " + sent).strip() if buf else sent
            if len(candidate) <= max_chars:
                buf = candidate
            else:
                if buf:
                    parts.append(buf)
                if len(sent) <= max_chars:
                    buf = sent
                else:
                    for i in range(0, len(sent), max_chars):
                        parts.append(sent[i : i + max_chars])
                    buf = ""
        if buf and len(buf) > max_chars * 0.7:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


async def synth_chunk(text: str, out_path: Path, sem: asyncio.Semaphore) -> None:
    async with sem:
        if out_path.exists() and out_path.stat().st_size > 1000:
            return
        for attempt in range(4):
            try:
                communicate = edge_tts.Communicate(text, VOICE, rate="-5%")
                await communicate.save(str(out_path))
                if out_path.stat().st_size > 500:
                    return
            except Exception as e:
                print(f"    retry {out_path.name} {attempt+1}: {e}", flush=True)
                await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Failed TTS for {out_path}")


async def synth_chapter(txt_path: Path, out_mp3: Path, sem: asyncio.Semaphore) -> None:
    if out_mp3.exists() and out_mp3.stat().st_size > 5000:
        print(f"SKIP existing {out_mp3.name}", flush=True)
        return

    raw = txt_path.read_text(encoding="utf-8")
    chunks = chunk_text(raw)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    tmp_files = [AUDIO_DIR / f"{txt_path.stem}_part{i:03d}.mp3" for i in range(len(chunks))]

    print(f"CHAPTER {txt_path.name} ({len(chunks)} parts)", flush=True)
    await asyncio.gather(
        *[synth_chunk(chunk, tmp, sem) for chunk, tmp in zip(chunks, tmp_files)]
    )

    if len(tmp_files) == 1:
        out_mp3.write_bytes(tmp_files[0].read_bytes())
        tmp_files[0].unlink(missing_ok=True)
        return

    list_file = AUDIO_DIR / f"{txt_path.stem}_concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in tmp_files), encoding="utf-8"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out_mp3),
        ],
        check=True,
        capture_output=True,
    )
    list_file.unlink(missing_ok=True)
    for p in tmp_files:
        p.unlink(missing_ok=True)
    print(f"  OK {out_mp3.name} ({out_mp3.stat().st_size} bytes)", flush=True)


async def main(only: list[str] | None = None) -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(CHAP_DIR.glob("*.txt"))
    if only:
        files = [f for f in files if f.stem in only]
    if not files:
        raise SystemExit("No Russian chapters found — run translate_ru.py first")

    sem = asyncio.Semaphore(CONCURRENCY)
    chapter_sem = asyncio.Semaphore(3)

    async def run_one(f: Path) -> Path:
        async with chapter_sem:
            out_mp3 = AUDIO_DIR / f"{f.stem}.mp3"
            await synth_chapter(f, out_mp3, sem)
            return out_mp3

    chapter_mp3s = await asyncio.gather(*[run_one(f) for f in files])
    chapter_mp3s = sorted(chapter_mp3s, key=lambda p: p.name)

    full = ROOT / "How_to_Build_a_Personal_Brand_AUDIOBOOK_RU.mp3"
    list_file = AUDIO_DIR / "_full_concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in chapter_mp3s), encoding="utf-8"
    )
    print("Concatenating full RU audiobook...", flush=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(full),
        ],
        check=True,
        capture_output=True,
    )
    art = Path("/opt/cursor/artifacts/personal_brand_audiobook")
    art.mkdir(parents=True, exist_ok=True)
    (art / full.name).write_bytes(full.read_bytes())
    # lite
    lite = art / "How_to_Build_a_Personal_Brand_AUDIOBOOK_RU_lite.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(full),
            "-ac",
            "1",
            "-ar",
            "22050",
            "-b:a",
            "32k",
            str(lite),
        ],
        check=True,
        capture_output=True,
    )
    print(f"DONE {full} ({full.stat().st_size} bytes)", flush=True)
    print(f"LITE {lite} ({lite.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    only = sys.argv[1:] or None
    asyncio.run(main(only))
