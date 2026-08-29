"""Read a shared Google Drive folder (no Google API key)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import codecs

import httpx

from .parse import ParseError

DEFAULT_FOLDER = "1VIxQOYkI8T5kGaO8EuzJEduuQBnLyRgj"
FOLDER_URL = f"https://drive.google.com/drive/folders/{DEFAULT_FOLDER}"
STATEMENT_EXT = {".pdf", ".csv", ".xlsx", ".xls", ".txt"}
MIME_OK = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass
class DriveFile:
    id: str
    name: str
    mime: str
    modified_ms: int = 0
    size: int = 0

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


def folder_id_from_env() -> str:
    raw = (os.getenv("FINANCE_DRIVE_FOLDER") or "").strip()
    if not raw:
        return DEFAULT_FOLDER
    return folder_id_from_value(raw)


def folder_id_from_value(raw: str) -> str:
    text = raw.strip()
    if re.fullmatch(r"[\w-]{20,}", text) and "http" not in text:
        return text
    parsed = urlparse(text)
    parts = [p for p in parsed.path.split("/") if p]
    if "folders" in parts:
        return parts[parts.index("folders") + 1]
    qs = parse_qs(parsed.query)
    if qs.get("id"):
        return qs["id"][0]
    raise ParseError("Не понял ссылку на папку Google Drive")


def list_folder(folder: str | None = None, *, client: httpx.Client | None = None) -> list[DriveFile]:
    fid = folder_id_from_value(folder) if folder else folder_id_from_env()
    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=30.0, headers=_headers())
    try:
        res = http.get(f"https://drive.google.com/drive/folders/{fid}")
        res.raise_for_status()
        files = parse_folder_html(res.text, folder_id=fid)
    finally:
        if own:
            http.close()
    files = [f for f in files if _is_statement(f)]
    files.sort(key=lambda f: (f.modified_ms, f.name), reverse=True)
    return files


def download_file(
    file: DriveFile,
    dest_dir: str | Path,
    *,
    client: httpx.Client | None = None,
) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(file.name) or f"{file.id}.bin"
    dest = dest_dir / safe
    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=60.0, headers=_headers())
    try:
        url = f"https://drive.google.com/uc?export=download&id={file.id}&confirm=t"
        res = http.get(url)
        res.raise_for_status()
        if "text/html" in res.headers.get("content-type", "") and b"%PDF" not in res.content[:8]:
            confirm = _confirm_url(res.text, file.id)
            if confirm:
                res = http.get(confirm)
                res.raise_for_status()
        dest.write_bytes(res.content)
    finally:
        if own:
            http.close()
    if dest.stat().st_size < 20:
        raise ParseError(f"Пустой файл с Диска: {file.name}")
    return dest


def parse_folder_html(html: str, *, folder_id: str = "") -> list[DriveFile]:
    files = _from_ivd(html, folder_id=folder_id)
    if files:
        return files
    return _from_markup(html)


def _unescape_js(raw: str) -> str:
    try:
        s = codecs.decode(raw.replace("\\/", "/"), "unicode_escape")
    except Exception:
        s = raw.replace("\\/", "/")
        s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)
        s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    if "Ð" in s or "Ñ" in s:
        try:
            s = s.encode("latin1").decode("utf-8")
        except UnicodeError:
            pass
    return s


def _from_ivd(html: str, *, folder_id: str) -> list[DriveFile]:
    m = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'((?:\\'|[^'])*)'", html)
    if not m:
        return []
    raw = m.group(1)
    s = _unescape_js(raw)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    rows = data[0] if isinstance(data, list) and data and isinstance(data[0], list) else []
    out: list[DriveFile] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        fid, parents, name, mime = row[0], row[1], row[2], row[3]
        if not isinstance(fid, str) or not fid.startswith("1"):
            continue
        if folder_id and isinstance(parents, list) and parents and folder_id not in parents:
            continue
        if not isinstance(name, str) or not isinstance(mime, str):
            continue
        modified = int(row[9]) if len(row) > 9 and isinstance(row[9], int) else 0
        size = int(row[13]) if len(row) > 13 and isinstance(row[13], int) else 0
        out.append(DriveFile(id=fid, name=name, mime=mime, modified_ms=modified, size=size))
    return out


def _from_markup(html: str) -> list[DriveFile]:
    out: list[DriveFile] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'aria-label="([^"]+?)\s+(PDF|CSV|XLSX|XLS|TXT)[^"]*".{0,400}?data-id="(1[^"]+)"',
        html,
        re.I | re.S,
    ):
        name, _kind, fid = m.group(1).strip(), m.group(2), m.group(3)
        if fid in seen:
            continue
        seen.add(fid)
        if Path(name).suffix.lower() not in STATEMENT_EXT and not name.lower().endswith(
            f".{_kind.lower()}"
        ):
            if _kind.lower() == "pdf" and not name.lower().endswith(".pdf"):
                name = f"{name}.pdf"
        out.append(DriveFile(id=fid, name=name, mime="application/octet-stream"))
    return out


def _is_statement(file: DriveFile) -> bool:
    if file.suffix in STATEMENT_EXT:
        return True
    return file.mime in MIME_OK and "folder" not in file.mime


def _confirm_url(html: str, file_id: str) -> str | None:
    m = re.search(r'href="(/uc\?export=download[^"]+confirm=[^"]+)"', html)
    if not m:
        return None
    href = m.group(1).replace("&amp;", "&")
    if file_id not in href:
        return None
    return "https://drive.google.com" + href


def _safe_name(name: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in ".-_ " else "_" for ch in Path(name).name)
    return keep.strip()[:120]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; kassa-pull/1.0)",
        "Accept-Language": "ru,en;q=0.8",
    }
