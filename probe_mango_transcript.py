#!/usr/bin/env python3
"""Probe Mango VPBX API for transcript-related endpoints (read-only)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mango_vpbx import MangoVpbxClient


def load_env() -> None:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def main() -> None:
    load_env()
    client = MangoVpbxClient(os.environ["MANGO_VPBX_API_KEY"], os.environ["MANGO_VPBX_API_SALT"])

    tz = ZoneInfo("Europe/Moscow")
    day = (datetime.now(tz) - timedelta(days=1)).date()
    start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    calls = client.fetch_stats(int(start.timestamp()), int(end.timestamp()), success=True)
    if not calls:
        print("No calls")
        return

    call = calls[0]
    rec_id = call.recording_ids[0] if call.recording_ids else ""
    entry_id = call.entry_id
    print(f"Probe call entry_id={entry_id} recording={rec_id[:40]}...")

    extra_fields = [
        "records,start,finish,answer,from_extension,from_number,to_extension,to_number,"
        "disconnect_reason,line_number,location,entry_id,transcript,text,dialog,speech,tags,topics"
    ]
    try:
        req = client.request_stats(int(start.timestamp()), int(end.timestamp()), fields=extra_fields)
        key = req.get("key")
        if key:
            import time

            time.sleep(3)
            raw = client.get_stats_result(key)
            print("EXTRA FIELDS stats sample:", str(raw)[:300])
    except Exception as exc:  # noqa: BLE001
        print("EXTRA FIELDS failed:", exc)

    paths = [
        ("queries/recording/post", {"recording_id": rec_id, "action": "download"}),
        ("queries/recording/post", {"recording_id": rec_id, "action": "play"}),
        ("queries/recording/transcription", {"recording_id": rec_id}),
        ("queries/recording/transcription", {"entry_id": entry_id}),
        ("queries/transcript", {"entry_id": entry_id}),
        ("queries/transcript", {"recording_id": rec_id}),
        ("queries/speech/transcript", {"entry_id": entry_id}),
        ("queries/speech/transcript", {"recording_id": rec_id}),
        ("queries/speech_analytics/transcript", {"entry_id": entry_id}),
        ("queries/speech_analytics/dialog", {"entry_id": entry_id}),
        ("queries/dialog", {"entry_id": entry_id}),
        ("queries/dialog", {"recording_id": rec_id}),
        ("result/stat", {"entry_id": entry_id}),
        ("result/call", {"entry_id": entry_id}),
    ]

    for path, payload in paths:
        if not rec_id and "recording_id" in payload:
            continue
        try:
            resp = client._post(path, payload)  # noqa: SLF001
            text = json.dumps(resp, ensure_ascii=False) if isinstance(resp, (dict, list)) else str(resp)
            snippet = text[:220].replace("\n", " ")
            has_text = any(
                w in text.lower()
                for w in ("транскрип", "расшифр", "dialog", "transcript", "speaker", "сотрудник", "клиент")
            )
            mark = " **MAYBE TEXT**" if has_text and len(text) > 80 else ""
            print(f"OK  {path} {list(payload.keys())}{mark}")
            print(f"    {snippet}")
        except Exception as exc:  # noqa: BLE001
            print(f"ERR {path} {payload} -> {exc}")


if __name__ == "__main__":
    main()
