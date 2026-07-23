#!/usr/bin/env python3
"""Daily Mango call pipeline: auto-select, DOCX export, Telegram send."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

from call_qc import CallAssessment, assess_call, format_day_summary
from mango_sync import fetch_site_day_calls, sync_day
from mango_vpbx import MangoVpbxClient
from telegram_format import build_call_message, format_date_no_year, format_time_short
from site_config import SiteConfig, load_sites
from telegram_notify import site_chat_ids
from transcript_utils import extract_datetime, parse_transcript_file, transcript_paragraphs

try:
    from docx import Document
except ImportError:
    Document = None  # type: ignore


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


def short_comment(category: str) -> str:
    c = category.lower()
    if "тех" in c:
        return "Проблема: сбой онлайн-записи. Нужно сразу переводить на ручное оформление."
    if "цена" in c:
        return "Проблема: риск потери на этапе цены. Нужен дожим до конкретного слота."
    if "не закрыт" in c or "не запис" in c:
        return "Проблема: клиент не закрыт в запись после звонка."
    if "перенос" in c or "отмен" in c:
        return "Проблема: перенос/отмена. Фиксируйте новую дату в этом же звонке."
    if "недовол" in c or "жалоб" in c:
        return "Проблема: недовольство клиента. Нужны извинение и конкретное решение."
    if "отказ" in c:
        return "Проблема: отказ в услуге. Важно предложить альтернативу."
    if "новый" in c:
        return "Фокус: первый контакт. Довести до записи и подтвердить шаг."
    return "Требуется контроль качества обработки звонка."


def auto_select(calls_dir: Path, report_date: str) -> List[Dict[str, str]]:
    """Pick bad/uncertain calls for one day only (filename prefix YYYY-MM-DD__)."""
    selected: List[Dict[str, str]] = []
    for html_path in sorted(calls_dir.glob(f"{report_date}__*.html")):
        if html_path.name.lower() == "index.html":
            continue
        transcript = parse_transcript_file(html_path)
        if not transcript:
            continue
        assessment = assess_call(transcript)
        if assessment.should_send:
            selected.append(
                {
                    "file": html_path.name,
                    "category": assessment.category,
                    "comment": assessment.comment,
                    "verdict": assessment.verdict,
                }
            )
        else:
            print(f"[SKIP good] {html_path.name} — {assessment.category}")
    return selected


def _parse_file_meta(file_name: str) -> Tuple[str, str, str]:
    """Return (date_str, time_hms, phone) from call filename."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})__(\d{2}-\d{2}-\d{2})__(\d+)__", file_name)
    if not m:
        return "", "", "unknown"
    date_str, time_key, phone = m.groups()
    return date_str, time_key.replace("-", ":"), phone


def write_docx(
    out_path: Path,
    date_str: str,
    time_str: str,
    direction: str,
    phone: str,
    transcript: List[Tuple[str, str]],
) -> None:
    if Document is None:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

    doc = Document()
    doc.add_heading(f"{format_date_no_year(date_str)} · {format_time_short(time_str)}", level=1)
    doc.add_paragraph(f"{direction} · {phone}")
    doc.add_paragraph("")
    doc.add_heading("Расшифровка", level=2)
    for line in transcript_paragraphs(transcript):
        doc.add_paragraph(line)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def load_state(state_path: Path) -> Dict[str, str]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(state_path: Path, state: Dict[str, str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def git_pull(base_dir: Path) -> None:
    if not (base_dir / ".git").exists():
        return
    subprocess.run(["git", "pull", "--ff-only"], cwd=base_dir, check=True)


def count_day_directions(day_calls: list) -> Tuple[int, int]:
    incoming = outgoing = 0
    for call in day_calls:
        fn = getattr(call, "from_number", "")
        tn = getattr(call, "to_number", "")
        if "sip:" in (tn or "") and "sip:" not in (fn or ""):
            incoming += 1
        elif "sip:" in (fn or "") and "sip:" not in (tn or ""):
            outgoing += 1
    return incoming, outgoing


def _safe_tg_broadcast_message(
    token: str,
    chat_ids: List[str],
    text: str,
    *,
    parse_mode: str | None = None,
) -> None:
    from telegram_notify import tg_broadcast_message

    try:
        tg_broadcast_message(token, chat_ids, text, parse_mode=parse_mode)
    except Exception as exc:
        print(f"[WARN] Telegram summary failed: {exc}")


def _safe_tg_broadcast_document(token: str, chat_ids: List[str], file_path: Path, caption: str) -> None:
    from telegram_notify import tg_broadcast_document

    try:
        tg_broadcast_document(token, chat_ids, file_path, caption)
    except Exception as exc:
        print(f"[WARN] Telegram document failed ({file_path.name}): {exc}")


def run_site_pipeline(
    site: SiteConfig,
    base: Path,
    *,
    report_date_str: str,
    report_date,
    tz: ZoneInfo,
    token: str,
    chat_ids: List[str],
    mango_sync: bool,
    dry_run: bool,
    force: bool,
) -> None:
    calls_dir = site.calls_dir(base)
    state_path = site.state_file(base)
    docx_dir = site.docx_dir(base)
    calls_dir.mkdir(parents=True, exist_ok=True)
    docx_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {site.label} ({site.site_id}) ===")

    day_dt = datetime(report_date.year, report_date.month, report_date.day)
    mango: MangoVpbxClient | None = None
    day_calls: list = []
    stats_unavailable = False
    try:
        mango = MangoVpbxClient(site.api_key, site.api_salt)
        day_calls = fetch_site_day_calls(mango, day_dt, site.tz_name, site_id=site.site_id)
    except Exception as exc:
        stats_unavailable = True
        print(f"[WARN] Mango stats ({site.site_id}): {exc}")

    if mango_sync:
        if mango is None:
            try:
                mango = MangoVpbxClient(site.api_key, site.api_salt)
            except Exception as exc:
                print(f"[WARN] Mango client ({site.site_id}): {exc}")
        if mango is not None:
            sa_endpoint = os.getenv("MANGO_SA_TRANSCRIPT_ENDPOINT", "").strip()
            yandex_client = None
            yandex_cache_dir = site.yandex_cache_dir(base)
            if os.getenv("YANDEX_STT_ENABLED", "").strip().lower() in ("1", "true", "yes"):
                from yandex_stt import YandexSttClient

                yandex_key = os.getenv("YANDEX_SPEECHKIT_API_KEY", "").strip()
                if yandex_key:
                    yandex_client = YandexSttClient(
                        yandex_key, os.getenv("YANDEX_FOLDER_ID", "").strip()
                    )
            try:
                stats = sync_day(
                    client=mango,
                    day=day_dt,
                    base_dir=base,
                    calls_dir=calls_dir,
                    webhooks_dir=site.webhooks_dir(base),
                    index_path=site.calls_index(base),
                    tz_name=site.tz_name,
                    line_number=site.line_number,
                    sa_endpoint=sa_endpoint,
                    min_duration=int(os.getenv("MANGO_MIN_DURATION", "30")),
                    force=force,
                    yandex_client=yandex_client,
                    yandex_cache_dir=yandex_cache_dir,
                    site_id=site.site_id,
                    prefetched_calls=[
                    c
                    for c in fetch_site_day_calls(
                        mango, day_dt, site.tz_name, site_id=site.site_id, success_only=True
                    )
                ]
                or None,
                )
                print(
                    f"[SYNC] {report_date_str} fetched={stats['fetched']} saved={stats['saved']} "
                    f"skipped={stats['skipped']} missing_transcript={stats['missing_transcript']}"
                )
            except Exception as exc:
                print(f"[WARN] Mango sync ({site.site_id}): {exc}")

    selected = auto_select(calls_dir, report_date_str)
    analyzed = len(
        [
            p
            for p in calls_dir.glob(f"{report_date_str}__*.html")
            if p.name.lower() != "index.html" and parse_transcript_file(p)
        ]
    )
    incoming, outgoing = count_day_directions(day_calls)
    summary_parse = "HTML" if stats_unavailable else None

    if not selected:
        print("[INFO] No problematic calls found.")
        if not dry_run and token and chat_ids:
            summary = format_day_summary(
                report_date_str,
                incoming,
                outgoing,
                analyzed,
                0,
                0,
                site_label=site.label,
                stats_unavailable=stats_unavailable,
            )
            _safe_tg_broadcast_message(token, chat_ids, summary, parse_mode=summary_parse)
            _safe_tg_broadcast_message(
                token, chat_ids, f"{site.label}\n\nКосячных звонков за день не найдено."
            )
        return

    state = load_state(state_path)
    to_send: List[Dict[str, str]] = []
    for item in selected:
        file_name = item["file"]
        html_path = calls_dir / file_name
        if not html_path.exists():
            continue
        key = f"{file_name}:{html_path.stat().st_mtime_ns}"
        if not force and state.get(file_name) == key:
            continue
        to_send.append(item)

    all_bad = sum(1 for item in selected if item.get("verdict") == "bad")
    all_uncertain = sum(1 for item in selected if item.get("verdict") == "uncertain")

    if not to_send:
        print("[INFO] Nothing new to send.")
        if not dry_run and token and chat_ids:
            summary = format_day_summary(
                report_date_str,
                incoming,
                outgoing,
                analyzed,
                all_bad,
                all_uncertain,
                site_label=site.label,
                stats_unavailable=stats_unavailable,
            )
            _safe_tg_broadcast_message(token, chat_ids, summary, parse_mode=summary_parse)
            if all_bad + all_uncertain:
                note = f"{site.label}\n\nКосячные звонки ({all_bad + all_uncertain}) уже были отправлены ранее."
            else:
                note = f"{site.label}\n\nКосячных звонков за день не найдено."
            _safe_tg_broadcast_message(token, chat_ids, note)
        return

    if not dry_run and (not token or not chat_ids):
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

    sent_bad = sum(1 for item in to_send if item.get("verdict") == "bad")
    sent_uncertain = sum(1 for item in to_send if item.get("verdict") == "uncertain")

    if not dry_run:
        summary = format_day_summary(
            report_date_str,
            incoming,
            outgoing,
            analyzed,
            sent_bad,
            sent_uncertain,
            site_label=site.label,
            stats_unavailable=stats_unavailable,
        )
        _safe_tg_broadcast_message(token, chat_ids, summary, parse_mode=summary_parse)

    sent = 0
    for idx, item in enumerate(to_send, start=1):
        file_name = item["file"]
        html_path = calls_dir / file_name
        transcript = parse_transcript_file(html_path)
        if not transcript:
            print(f"[WARN] Empty transcript: {file_name}")
            continue

        assessment = assess_call(transcript)
        date_str, time_hms, phone = _parse_file_meta(file_name)
        if not date_str:
            date_str = report_date.isoformat()
            time_hms = extract_datetime(file_name).split(" ", 1)[-1] if " " in extract_datetime(file_name) else "00:00:00"

        docx_name = f"call_{idx:02d}_{Path(file_name).stem}.docx"
        docx_path = docx_dir / docx_name
        write_docx(docx_path, date_str, time_hms, "входящий", phone, transcript)

        comment = build_call_message(
            assessment,
            date_str=date_str,
            time_hms=time_hms,
            direction="входящий",
            phone=phone,
            site_label=site.label,
        )

        if dry_run:
            print(f"[DRY-RUN] {file_name} -> {docx_path.name}")
            continue

        _safe_tg_broadcast_message(token, chat_ids, comment)
        _safe_tg_broadcast_document(token, chat_ids, docx_path, site.label)
        state[file_name] = f"{file_name}:{html_path.stat().st_mtime_ns}"
        sent += 1
        print(f"[OK] Sent {file_name}")

    if not dry_run:
        save_state(state_path, state)
        print(f"[DONE] {site.site_id}: sent {sent} calls (bad={sent_bad}, uncertain={sent_uncertain}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Mango call pipeline")
    parser.add_argument("--base-dir", default=".", help="Project/calls directory")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--git-pull", action="store_true")
    parser.add_argument("--mango-sync", action="store_true", help="Fetch calls from Mango VPBX API first")
    parser.add_argument("--mango-days", type=int, default=1, help="Days back for report date per site TZ")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Resend even if already sent")
    parser.add_argument("--site", default="", help="Only this site (moscow, krasnoyarsk)")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    load_dotenv(base / args.dotenv)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if args.git_pull:
        git_pull(base)

    sites = load_sites()
    if args.site:
        sites = [s for s in sites if s.site_id == args.site.strip().lower()]
        if not sites:
            raise SystemExit(f"Site not configured: {args.site}")

    if not sites:
        raise SystemExit("No Mango sites configured. Set MANGO_SITES and SITE_* keys in .env")

    for site in sites:
        tz = ZoneInfo(site.tz_name)
        report_date = (datetime.now(tz) - timedelta(days=max(args.mango_days, 1))).date()
        report_date_str = report_date.isoformat()
        chat_ids = site_chat_ids(site)
        run_site_pipeline(
            site,
            base,
            report_date_str=report_date_str,
            report_date=report_date,
            tz=tz,
            token=token,
            chat_ids=chat_ids,
            mango_sync=args.mango_sync,
            dry_run=args.dry_run,
            force=args.force,
        )
        if args.mango_sync:
            time.sleep(15)


if __name__ == "__main__":
    main()
