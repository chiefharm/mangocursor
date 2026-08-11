#!/usr/bin/env python3
"""Translate EN chapter texts to RU (Google via deep-translator)."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from deep_translator import GoogleTranslator

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "chapters"
DST = ROOT / "chapters_ru"
MAX = 4200  # Google soft limit ~5k chars


def chunks(text: str, max_len: int = MAX) -> list[str]:
    text = text.strip()
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    buf = ""
    for para in paras:
        # further split long paragraphs by sentences
        sents = re.split(r"(?<=[.!?…])\s+", para)
        for sent in sents:
            if not sent:
                continue
            cand = (buf + " " + sent).strip() if buf else sent
            if len(cand) <= max_len:
                buf = cand
            else:
                if buf:
                    parts.append(buf)
                if len(sent) <= max_len:
                    buf = sent
                else:
                    for i in range(0, len(sent), max_len):
                        parts.append(sent[i : i + max_len])
                    buf = ""
        if buf and len(buf) > max_len * 0.65:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


def translate_text(text: str, retries: int = 5) -> str:
    translator = GoogleTranslator(source="en", target="ru")
    out: list[str] = []
    for i, piece in enumerate(chunks(text)):
        for attempt in range(retries):
            try:
                ru = translator.translate(piece)
                if not ru:
                    raise RuntimeError("empty translation")
                out.append(ru)
                time.sleep(0.35)
                break
            except Exception as e:
                wait = 2 * (attempt + 1)
                print(f"  retry piece {i+1} attempt {attempt+1}: {e}", flush=True)
                time.sleep(wait)
        else:
            raise RuntimeError(f"failed to translate piece {i+1}")
    return "\n\n".join(out)


def main(only: list[str] | None = None) -> None:
    DST.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.txt"))
    if only:
        files = [f for f in files if f.stem in only]
    for f in files:
        out = DST / f.name
        if out.exists() and out.stat().st_size > 200:
            print(f"SKIP {f.name}", flush=True)
            continue
        raw = f.read_text(encoding="utf-8")
        print(f"TRANSLATE {f.name} ({len(raw)} chars)...", flush=True)
        ru = translate_text(raw)
        out.write_text(ru, encoding="utf-8")
        print(f"  OK {out.name} ({len(ru)} chars, {len(ru.split())} words)", flush=True)


if __name__ == "__main__":
    only = sys.argv[1:] or None
    main(only)
