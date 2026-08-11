#!/usr/bin/env python3
"""Generate chapter MP3s via edge-tts, then concat into one audiobook."""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent
CHAP_DIR = ROOT / "chapters"
AUDIO_DIR = ROOT / "audio_chapters"
VOICE = "en-US-AndrewNeural"  # clear long-form male narration
MAX_CHARS = 2800  # keep SSML/request payloads modest


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    # Split on paragraph / sentence boundaries
    parts: list[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buf = ""
    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", para)
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
                    # hard wrap very long sentences
                    for i in range(0, len(sent), max_chars):
                        parts.append(sent[i : i + max_chars])
                    buf = ""
        if buf and len(buf) > max_chars * 0.7:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


async def synth_chunk(text: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, VOICE, rate="-5%")
    await communicate.save(str(out_path))


async def synth_chapter(txt_path: Path, out_mp3: Path) -> None:
    raw = txt_path.read_text(encoding="utf-8")
    chunks = chunk_text(raw)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    tmp_files: list[Path] = []
    for i, chunk in enumerate(chunks):
        tmp = AUDIO_DIR / f"{txt_path.stem}_part{i:03d}.mp3"
        if tmp.exists() and tmp.stat().st_size > 1000:
            tmp_files.append(tmp)
            continue
        print(f"  TTS {txt_path.stem} part {i+1}/{len(chunks)} ({len(chunk)} chars)", flush=True)
        for attempt in range(3):
            try:
                await synth_chunk(chunk, tmp)
                break
            except Exception as e:
                print(f"    retry {attempt+1}: {e}", flush=True)
                await asyncio.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed TTS for {txt_path} part {i}")
        tmp_files.append(tmp)

    if len(tmp_files) == 1:
        tmp_files[0].replace(out_mp3)
        return

    # concat with ffmpeg
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


async def main(only: list[str] | None = None) -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(CHAP_DIR.glob("*.txt"))
    if only:
        files = [f for f in files if f.stem in only]
    chapter_mp3s: list[Path] = []
    for f in files:
        out_mp3 = AUDIO_DIR / f"{f.stem}.mp3"
        if out_mp3.exists() and out_mp3.stat().st_size > 5000:
            print(f"SKIP existing {out_mp3.name}", flush=True)
        else:
            print(f"CHAPTER {f.name}", flush=True)
            await synth_chapter(f, out_mp3)
        chapter_mp3s.append(out_mp3)

    # Full audiobook concat
    full = ROOT / "How_to_Build_a_Personal_Brand_AUDIOBOOK.mp3"
    list_file = AUDIO_DIR / "_full_concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in chapter_mp3s), encoding="utf-8"
    )
    print("Concatenating full audiobook...", flush=True)
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
    print(f"DONE {full} ({full.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    only = sys.argv[1:] or None
    asyncio.run(main(only))
