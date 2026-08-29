"""Pull new bank statements from the shared Google Drive folder."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .drive import DriveFile, download_file, folder_id_from_env, list_folder
from .parse import ParseError, parse_statement
from .store import FinanceStore, ImportResult

DEFAULT_FOLDER_URL = "https://drive.google.com/drive/folders/1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"


def pull_statements(
    store: FinanceStore,
    *,
    dest_dir: str | Path,
    folder: str | None = None,
    dry_run: bool = False,
) -> dict:
    files = list_folder(folder)
    if not files:
        return {
            "ok": True,
            "files": [],
            "new_count": 0,
            "dup_count": 0,
            "review_count": 0,
            "period_from": None,
            "period_to": None,
            "newest": None,
            "dry_run": dry_run,
        }

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    new_count = dup_count = review_count = 0
    periods: list[str] = []

    for file in files:
        local = download_file(file, dest_dir)
        try:
            txs = parse_statement(local, filename=file.name)
        except ParseError as exc:
            reports.append(
                {
                    "id": file.id,
                    "filename": file.name,
                    "error": str(exc),
                    "new_count": 0,
                    "dup_count": 0,
                    "review_count": 0,
                    "period_from": None,
                    "period_to": None,
                }
            )
            continue
        dates = [tx.posted_date.isoformat() for tx in txs]
        period_from = min(dates) if dates else None
        period_to = max(dates) if dates else None
        if dry_run:
            review = sum(1 for tx in txs if tx.needs_review)
            reports.append(
                {
                    "id": file.id,
                    "filename": file.name,
                    "new_count": len(txs),
                    "dup_count": 0,
                    "review_count": review,
                    "period_from": period_from,
                    "period_to": period_to,
                    "dry_run": True,
                }
            )
            new_count += len(txs)
            review_count += review
        else:
            result: ImportResult = store.import_transactions(txs, file.name)
            reports.append(_import_report(file, result))
            new_count += result.new_count
            dup_count += result.dup_count
            review_count += result.review_count
            period_from = result.period_from
            period_to = result.period_to
        if period_from:
            periods.append(period_from)
        if period_to:
            periods.append(period_to)

    newest = _newest_file(reports)
    return {
        "ok": True,
        "folder": folder or folder_id_from_env(),
        "files": reports,
        "new_count": new_count,
        "dup_count": dup_count,
        "review_count": review_count,
        "period_from": min(periods) if periods else None,
        "period_to": max(periods) if periods else None,
        "newest": newest,
        "dry_run": dry_run,
    }


def _import_report(file: DriveFile, result: ImportResult) -> dict:
    return {
        "id": file.id,
        "filename": result.filename,
        "new_count": result.new_count,
        "dup_count": result.dup_count,
        "review_count": result.review_count,
        "period_from": result.period_from,
        "period_to": result.period_to,
    }


def _newest_file(reports: list[dict]) -> dict | None:
    dated = [r for r in reports if r.get("period_to")]
    if not dated:
        return reports[0] if reports else None
    return max(dated, key=lambda r: r["period_to"])


def month_of(iso: str | None) -> tuple[int, int] | None:
    if not iso:
        return None
    d = date.fromisoformat(iso[:10])
    return d.year, d.month


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Забрать выписки с Google Drive")
    parser.add_argument("--folder", default="", help=f"ID или ссылка на папку (по умолчанию {DEFAULT_FOLDER_URL})")
    parser.add_argument("--dry-run", action="store_true", help="Только прочитать, не писать в кассу")
    args = parser.parse_args(argv)

    from .main import DB_PATH, UPLOAD_DIR, store

    folder = args.folder or None
    result = pull_statements(store, dest_dir=UPLOAD_DIR, folder=folder, dry_run=args.dry_run)
    print(f"папка: {result.get('folder')}")
    if not result["files"]:
        print("файлов выписок нет")
        return 0
    for item in result["files"]:
        if item.get("error"):
            print(f"  {item['filename']}: ошибка — {item['error']}")
            continue
        period = ""
        if item.get("period_from"):
            period = f"{item['period_from']}…{item['period_to']}"
        print(
            f"  {item['filename']}: {period}  "
            f"новых {item['new_count']}, дублей {item['dup_count']}, "
            f"без статьи {item['review_count']}"
        )
    newest = result.get("newest") or {}
    if newest.get("period_to"):
        print(f"новее по операциям внутри файла: до {newest['period_to']} ({newest.get('filename')})")
    print(f"итого новых {result['new_count']}, дублей {result['dup_count']}")
    print(f"база: {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
