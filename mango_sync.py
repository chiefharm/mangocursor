#!/usr/bin/env python3
"""Fetch Mango calls via VPBX API and store transcript HTML for the pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mango_vpbx import CallRecord, MangoVpbxClient, MangoVpbxError
from site_lines import is_tracked_call
from transcript_utils import (
    build_transcript_html,
    call_file_name,
    format_mango_header_dt,
    refine_segments,
    segments_from_webhook,
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_index(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_index(path: Path, index: Dict[str, Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def day_bounds(day: datetime, tz_name: str) -> Tuple[int, int]:
    if tz_name.upper() == "UTC":
        tz = timezone.utc
    else:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone(timedelta(hours=3))
    start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return int(start.timestamp()), int(end.timestamp())


def webhook_payload_path(webhooks_dir: Path, entry_id: str) -> Path:
    return webhooks_dir / f"{entry_id}.json"


def find_existing_html(calls_dir: Path, entry_id: str, index: Dict[str, Dict[str, str]]) -> Optional[Path]:
    mapped = index.get(entry_id, {}).get("file")
    if mapped:
        path = calls_dir / mapped
        if path.exists():
            return path
    for html_path in calls_dir.glob("*.html"):
        if html_path.name.lower() == "index.html":
            continue
        if entry_id in html_path.read_text(encoding="utf-8", errors="ignore"):
            return html_path
    return None


def transcript_from_webhook(webhooks_dir: Path, entry_id: str) -> Optional[List[Tuple[str, str, str]]]:
    path = webhook_payload_path(webhooks_dir, entry_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = segments_from_webhook(payload)
    return segments or None


def transcript_from_sa_api(
    client: MangoVpbxClient,
    call: CallRecord,
    sa_endpoint: str,
) -> Optional[List[Tuple[str, str, str]]]:
    """Optional Speech Analytics endpoint (configure after Mango support reply)."""
    if not sa_endpoint:
        return None
    payload = {"entry_id": call.entry_id, "recording_id": call.recording_ids[:1]}
    try:
        result = client._post(sa_endpoint.lstrip("/"), payload)  # noqa: SLF001
    except MangoVpbxError:
        return None
    if isinstance(result, dict):
        segments = segments_from_webhook(result)
        return segments or None
    return None


def build_html_for_call(
    call: CallRecord,
    segments: List[Tuple[str, str, str]],
    line_number: str,
) -> str:
    caller = call.client_number
    callee = call.employee_label
    return build_transcript_html(
        call_dt=format_mango_header_dt(call.start),
        line_number=line_number,
        caller=caller,
        callee=callee,
        duration_sec=call.duration_sec,
        segments=refine_segments(segments),
    )


def transcript_from_yandex(
    mango_client: MangoVpbxClient,
    yandex_client: Any,
    call: CallRecord,
    cache_dir: Path,
) -> Optional[List[Tuple[str, str, str]]]:
    if not call.recording_ids:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{call.entry_id}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        segments = [(s[0], s[1], s[2]) for s in cached.get("segments", [])]
        return segments or None

    recording_id = mango_client.normalize_recording_id(call.recording_ids[0])
    try:
        audio = mango_client.download_recording(recording_id)
    except MangoVpbxError as exc:
        print(f"[WARN] Mango recording download failed for {call.entry_id}: {exc}")
        return None
    mp3_path = cache_dir / f"{call.entry_id}.mp3"
    mp3_path.write_bytes(audio)

    from yandex_stt import YandexSttError

    try:
        segments = yandex_client.transcribe_mp3(audio, call_start_ts=call.start)
    except YandexSttError as exc:
        print(f"[WARN] Yandex STT failed for {call.entry_id}: {exc}")
        return None

    cache_path.write_text(
        json.dumps({"segments": segments, "recording_id": recording_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return segments


def sync_day(
    *,
    client: MangoVpbxClient,
    day: datetime,
    base_dir: Path,
    calls_dir: Path,
    webhooks_dir: Path,
    index_path: Path,
    tz_name: str,
    line_number: str,
    sa_endpoint: str,
    min_duration: int,
    force: bool,
    yandex_client: Any = None,
    yandex_cache_dir: Path | None = None,
    site_id: str = "",
    prefetched_calls: List[CallRecord] | None = None,
) -> Dict[str, int]:
    date_from, date_to = day_bounds(day, tz_name)
    if prefetched_calls is not None:
        calls = prefetched_calls
    else:
        calls = client.fetch_stats(date_from, date_to, success=True)
    index = load_index(index_path)

    stats = {"fetched": len(calls), "saved": 0, "skipped": 0, "missing_transcript": 0, "filtered": 0}

    for call in calls:
        if site_id and not is_tracked_call(site_id, call):
            stats["filtered"] += 1
            continue
        if call.duration_sec < min_duration:
            stats["skipped"] += 1
            continue

        existing = find_existing_html(calls_dir, call.entry_id, index)
        if existing and not force:
            index[call.entry_id] = {
                "file": existing.name,
                "start": str(call.start),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            stats["skipped"] += 1
            continue

        segments = transcript_from_webhook(webhooks_dir, call.entry_id)
        if not segments:
            segments = transcript_from_sa_api(client, call, sa_endpoint)
        if not segments and yandex_client is not None and yandex_cache_dir is not None:
            segments = transcript_from_yandex(client, yandex_client, call, yandex_cache_dir)

        if not segments:
            stats["missing_transcript"] += 1
            meta_path = base_dir / "data" / "calls" / f"{call.entry_id}.json"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(
                json.dumps(
                    {
                        "entry_id": call.entry_id,
                        "start": call.start,
                        "finish": call.finish,
                        "from_number": call.from_number,
                        "to_number": call.to_number,
                        "recording_ids": call.recording_ids,
                        "employee": call.employee_label,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            continue

        file_name = call_file_name(call.start, call.client_number, call.employee_label)
        out_path = calls_dir / file_name
        html = build_html_for_call(call, segments, line_number)
        out_path.write_text(html, encoding="utf-8")

        index[call.entry_id] = {
            "file": file_name,
            "start": str(call.start),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        stats["saved"] += 1

    save_index(index_path, index)
    return stats


def fetch_site_day_calls(
    client: MangoVpbxClient,
    day: datetime,
    tz_name: str,
    *,
    site_id: str = "",
    success_only: bool = False,
) -> List[CallRecord]:
    """Fetch Mango stats once for a calendar day (optionally filter tracked branches)."""
    from zoneinfo import ZoneInfo

    date_from, date_to = day_bounds(day, tz_name)
    tz = ZoneInfo(tz_name)
    filters: Dict[str, Any] = {}
    if success_only:
        filters["success"] = True
    calls = client.fetch_stats(date_from, date_to, **filters)
    day_calls = [
        c for c in calls if datetime.fromtimestamp(c.start, tz).date() == day.date()
    ]
    if site_id:
        day_calls = [c for c in day_calls if is_tracked_call(site_id, c)]
    return day_calls


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Mango calls and transcripts")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--calls-dir", default="", help="Where to save HTML transcripts")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--days", type=int, default=1, help="How many past days to sync")
    parser.add_argument("--date", default="", help="Single day YYYY-MM-DD (overrides --days)")
    parser.add_argument("--tz", default="Europe/Moscow")
    parser.add_argument("--min-duration", type=int, default=30, help="Skip calls shorter than N sec")
    parser.add_argument("--force", action="store_true", help="Rewrite HTML even if file exists")
    parser.add_argument(
        "--yandex",
        action="store_true",
        help="Transcribe Mango MP3 via Yandex SpeechKit (needs YANDEX_SPEECHKIT_API_KEY)",
    )
    parser.add_argument(
        "--site",
        default="",
        help="Site id from MANGO_SITES (moscow, krasnoyarsk). Uses legacy MANGO_VPBX_* if omitted.",
    )
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    load_dotenv(base / args.dotenv)

    site = None
    if args.site:
        from site_config import get_site

        site = get_site(args.site)

    if site:
        calls_dir = site.calls_dir(base)
        webhooks_dir = site.webhooks_dir(base)
        index_path = site.calls_index(base)
        api_key = site.api_key
        api_salt = site.api_salt
        line_number = site.line_number
        tz_default = site.tz_name
        yandex_cache_dir = site.yandex_cache_dir(base)
        print(f"[SITE] {site.site_id} — {site.label} (ЛС {site.account})")
    else:
        calls_dir = Path(args.calls_dir).resolve() if args.calls_dir else base
        webhooks_dir = base / "data" / "webhooks"
        index_path = base / "data" / "calls_index.json"
        api_key = os.getenv("MANGO_VPBX_API_KEY", "").strip()
        api_salt = os.getenv("MANGO_VPBX_API_SALT", "").strip()
        line_number = os.getenv("MANGO_LINE_NUMBER", "sip:so1297co@vpbx400310395.mangosip.ru").strip()
        tz_default = args.tz
        yandex_cache_dir = base / "data" / "yandex_cache"

    sa_endpoint = os.getenv("MANGO_SA_TRANSCRIPT_ENDPOINT", "").strip()

    if not api_key or not api_salt:
        raise SystemExit(
            "Set MANGO_VPBX_API_KEY and MANGO_VPBX_API_SALT in .env "
            "(ЛК Mango → Интеграции → API коннектор)."
        )

    client = MangoVpbxClient(api_key, api_salt)

    yandex_client = None
    yandex_cache_dir.mkdir(parents=True, exist_ok=True)
    if args.yandex or os.getenv("YANDEX_STT_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        from yandex_stt import YandexSttClient, YandexSttError

        yandex_key = os.getenv("YANDEX_SPEECHKIT_API_KEY", "").strip()
        if not yandex_key:
            raise SystemExit("Set YANDEX_SPEECHKIT_API_KEY in .env (Yandex Cloud → SpeechKit → API key)")
        try:
            yandex_client = YandexSttClient(yandex_key, os.getenv("YANDEX_FOLDER_ID", "").strip())
        except YandexSttError as exc:
            raise SystemExit(str(exc)) from exc

    if args.date:
        days = [datetime.strptime(args.date, "%Y-%m-%d")]
    else:
        tz = ZoneInfo(tz_default)
        today = datetime.now(tz)
        days = [today - timedelta(days=offset) for offset in range(1, args.days + 1)]

    site_id = args.site.strip().lower() if args.site else ""

    total = {"fetched": 0, "saved": 0, "skipped": 0, "missing_transcript": 0, "filtered": 0}
    for day in days:
        print(f"[SYNC] {day.strftime('%Y-%m-%d')}")
        try:
            stats = sync_day(
                client=client,
                day=day,
                base_dir=base,
                calls_dir=calls_dir,
                webhooks_dir=webhooks_dir,
                index_path=index_path,
                tz_name=tz_default,
                line_number=line_number,
                sa_endpoint=sa_endpoint,
                min_duration=args.min_duration,
                force=args.force,
                yandex_client=yandex_client,
                yandex_cache_dir=yandex_cache_dir,
                site_id=site_id,
            )
        except MangoVpbxError as exc:
            print(f"[ERROR] {exc}")
            continue
        for key, value in stats.items():
            total[key] += value
        print(
            f"  fetched={stats['fetched']} saved={stats['saved']} "
            f"skipped={stats['skipped']} filtered={stats.get('filtered', 0)} "
            f"missing_transcript={stats['missing_transcript']}"
        )

    print(
        f"[DONE] fetched={total['fetched']} saved={total['saved']} "
        f"skipped={total['skipped']} missing_transcript={total['missing_transcript']}"
    )
    if total["missing_transcript"]:
        if yandex_client:
            print("[INFO] Some calls could not be transcribed. Check Yandex API key/billing.")
        else:
            print(
                "[INFO] VPBX API returns call list and recordings, but not speech-analytics text. "
                "Run with --yandex or set YANDEX_STT_ENABLED=1 (see YANDEX_STT_SETUP.md)."
            )


if __name__ == "__main__":
    main()
