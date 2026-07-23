#!/usr/bin/env python3
"""Download yesterday Mango calls and transcribe MP3 (Whisper local fallback)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mango_vpbx import MangoVpbxClient
from transcript_utils import build_transcript_html, call_file_name, format_mango_header_dt


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def transcribe_whisper(mp3_path: Path, model_name: str = "small") -> list[tuple[str, str, str]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(mp3_path), language="ru", vad_filter=True)
    out: list[tuple[str, str, str]] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        mm = int(seg.start) // 60
        ss = int(seg.start) % 60
        out.append(("Участник", f"{mm:02d}:{ss:02d}", seg.text.strip()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--model", default="small")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    load_dotenv(base / ".env")
    client = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])
    line_number = os.getenv("MANGO_LINE_NUMBER", "sip:so1297co@vpbx400310395.mangosip.ru")

    tz = ZoneInfo("Europe/Moscow")
    day = (datetime.now(tz) - timedelta(days=args.days)).date()
    start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    calls = client.fetch_stats(int(start.timestamp()), int(end.timestamp()), success=True)

    out_dir = base / "data" / "recordings" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []

    for call in calls:
        if call.duration_sec < 20 or not call.recording_ids:
            continue
        rid = client.normalize_recording_id(call.recording_ids[0])
        mp3 = out_dir / f"{call.entry_id}.mp3"
        if not mp3.exists():
            print(f"[DL] {rid[:24]}...")
            mp3.write_bytes(client.download_recording(rid))

        print(f"[STT] {mp3.name} ({call.duration_sec}s)...")
        segments = transcribe_whisper(mp3, args.model)
        html_name = call_file_name(call.start, call.client_number, call.employee_label)
        html_path = base / html_name
        html_path.write_text(
            build_transcript_html(
                call_dt=format_mango_header_dt(call.start),
                line_number=line_number,
                caller=call.client_number,
                callee=call.employee_label,
                duration_sec=call.duration_sec,
                segments=segments,
            ),
            encoding="utf-8",
        )
        report.append(
            {
                "time": format_mango_header_dt(call.start),
                "phone": call.client_number,
                "employee": call.employee_label,
                "duration_sec": call.duration_sec,
                "file": html_name,
                "segments": segments,
            }
        )

    summary_path = out_dir / "transcripts.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] {len(report)} calls -> {summary_path}")


if __name__ == "__main__":
    main()
