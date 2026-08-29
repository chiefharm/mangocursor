#!/usr/bin/env python3
"""Rebuild SOCO portfolio: Vigbo parse, content dedupe, JPEG thumbs, curated curls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (compatible; SOCO-TryOn/1.4)"}

OUT = Path(os.getenv("TRYON_PORTFOLIO_OUT", "/opt/soco-tryon/static/portfolio"))
MANIFEST = OUT / "manifest.json"
THUMB_SIDE = 420
FULL_SIDE = 900
JPEG_Q_THUMB = 70
JPEG_Q_FULL = 82

CATEGORIES = {
    "men": {
        "title": "Мужские стрижки",
        "pages": [
            "https://soco-moscow.ru/portfoliomenmebversion",
            "https://soco-kras.ru/portfoliomenmebversion",
        ],
        "max": 16,
    },
    "women": {
        "title": "Женские стрижки",
        "pages": [
            "https://soco-moscow.ru/portfoliowomen",
            "https://soco-kras.ru/portfoliowomen",
        ],
        "max": 16,
    },
    "color": {
        "title": "Окрашивание волос",
        "pages": ["https://soco-moscow.ru/portfoliocolor"],
        "max": 16,
    },
}

CURL_HASHES: set[str] = {
    h.strip().lower()
    for h in os.getenv(
        "TRYON_CURL_HASHES",
        ",".join(
            [
                # curated curly / perm looks from SOCO Vigbo galleries
                "6bcc6b6e40e318b6542a9730230f93c5",
                "3dfcd9aa72e9fe69c3be554fcd40e961",
                "cf37997299bcf7e41c14be6a77605985",
                "c804482d0aa81aa59803a75561454e7f",
                "3b6e9360af1ffc323f932eb512d338f5",
                "cf0ab304e14d3a1d20fc6d533801f05b",
                "c453657526d3991c9ec9f939815d2919",
                "56465527eaf0f2641db8c907e4fff19b",
            ]
        ),
    ).split(",")
    if len(h.strip()) >= 16
}


def fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, context=CTX, timeout=45) as r:
            if r.status >= 400:
                return None
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print("FAIL", url, exc)
        return None


def fetch_bytes(url: str) -> bytes | None:
    candidates = [url]
    if "/1000-" in url:
        candidates.append(url.replace("/1000-", "/"))
    last = None
    for cand in candidates:
        try:
            req = urllib.request.Request(cand, headers=UA)
            with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
                data = r.read()
            if data and len(data) > 2500:
                return data
        except Exception as exc:
            last = exc
    return None


def file_hash(text: str) -> str:
    m = re.search(r"([a-f0-9]{32})", text.lower())
    return m.group(1) if m else text.lower().split("/")[-1]


def content_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def normalize_storage(raw: str) -> str:
    s = raw.replace("\\/", "/")
    if s.startswith("//"):
        s = "https:" + s
    if not s.endswith("/"):
        s += "/"
    return s


def vigbo_urls(html: str) -> list[str]:
    """Resolve Vigbo gallery files against storages found on the page."""
    storages = [
        normalize_storage(s)
        for s in re.findall(r'"storage"\s*:\s*"([^"]+)"', html)
        if "cdn-st3.vigbo.com" in s.replace("\\/", "/")
    ]
    # also folder prefixes from absolute CDN urls
    for m in re.findall(
        r'((?:https?:)?//cdn-st3\.vigbo\.com/[^"\\]+?/)\d{0}(?:1000-)?socokrsk-',
        html,
        flags=re.I,
    ):
        storages.append(normalize_storage(m.replace("\\/", "/")))
    for m in re.findall(
        r'((?:https?:)?//cdn-st3\.vigbo\.com/[^"\\]+?/)',
        html,
        flags=re.I,
    ):
        u = normalize_storage(m.replace("\\/", "/"))
        if "/logo/" in u:
            continue
        if u not in storages:
            storages.append(u)

    # unique preserve order
    seen_st: set[str] = set()
    storages_u = []
    for s in storages:
        if s not in seen_st:
            seen_st.add(s)
            storages_u.append(s)

    files = re.findall(
        r'"file"\s*:\s*"((?:1000-)?socokrsk-[a-f0-9]{32}\.(?:jpe?g|png|webp))"',
        html,
        flags=re.I,
    )
    # also absolute urls
    absolutes = []
    for m in re.findall(
        r'(?:https?:)?//cdn-st3\.vigbo\.com/[^"\\]+\.(?:jpe?g|png|webp)',
        html,
        flags=re.I,
    ):
        u = m.replace("\\/", "/")
        if u.startswith("//"):
            u = "https:" + u
        if "/logo/" in u.lower():
            continue
        absolutes.append(u)

    urls: list[str] = []
    seen: set[str] = set()

    for u in absolutes:
        fh = file_hash(u)
        if fh in seen:
            continue
        seen.add(fh)
        urls.append(u)

    for name in files:
        fh = file_hash(name)
        if fh in seen:
            continue
        fname = name if name.lower().startswith("1000-") else f"1000-{name}"
        # Prefer storage that appears closest before this filename in HTML
        pos = html.lower().find(name.lower())
        best = None
        best_dist = 10**9
        for st in storages_u:
            # find last storage occurrence before file
            needle = st.replace("https:", "").rstrip("/")
            # search escaped and plain
            for variant in (st, st.replace("https:", ""), st.replace("/", "\\/")):
                idx = 0
                last = -1
                while True:
                    j = html.find(variant, idx)
                    if j < 0 or (pos >= 0 and j > pos):
                        break
                    last = j
                    idx = j + 1
                if last >= 0 and pos >= 0:
                    dist = pos - last
                    if 0 <= dist < best_dist:
                        best_dist = dist
                        best = st
        candidates = []
        if best:
            candidates.append(best + fname)
        for st in storages_u:
            u = st + fname
            if u not in candidates:
                candidates.append(u)
        # Probe until one works (HEAD-ish via range get)
        resolved = None
        for u in candidates[:8]:
            data = fetch_bytes(u)
            if data:
                # put back for later? We'll re-download in build — cache in memory map
                resolved = u
                # stash bytes on function attr cache
                _BYTE_CACHE[u] = data
                break
        if not resolved:
            print("UNRESOLVED", fh[:8])
            continue
        seen.add(fh)
        urls.append(resolved)
    return urls


_BYTE_CACHE: dict[str, bytes] = {}


def get_bytes(url: str) -> bytes | None:
    if url in _BYTE_CACHE:
        return _BYTE_CACHE[url]
    data = fetch_bytes(url)
    if data:
        _BYTE_CACHE[url] = data
    else:
        print("DL_FAIL", url[-70:])
    return data


def to_jpeg(data: bytes, max_side: int, quality: int) -> bytes:
    img = Image.open(BytesIO(data))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / m
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def wipe_cat(cat_dir: Path) -> None:
    cat_dir.mkdir(parents=True, exist_ok=True)
    for p in cat_dir.glob("*"):
        if p.is_file():
            p.unlink()


def save_item(cat: str, idx: int, data: bytes, source_url: str, cat_dir: Path) -> dict:
    full = to_jpeg(data, FULL_SIDE, JPEG_Q_FULL)
    thumb = to_jpeg(data, THUMB_SIDE, JPEG_Q_THUMB)
    name = f"{cat}_{idx:02d}.jpg"
    thumb_name = f"{cat}_{idx:02d}_t.jpg"
    (cat_dir / name).write_bytes(full)
    (cat_dir / thumb_name).write_bytes(thumb)
    return {
        "id": f"{cat}_{idx:02d}",
        "src": f"/static/portfolio/{cat}/{name}",
        "thumb": f"/static/portfolio/{cat}/{thumb_name}",
        "source_url": source_url,
        "file_hash": file_hash(source_url),
    }


def collect_urls(pages: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for page in pages:
        html = fetch(page)
        if not html:
            continue
        got = vigbo_urls(html)
        print("PAGE", page, "urls", len(got))
        for u in got:
            k = file_hash(u)
            if k in seen:
                continue
            seen.add(k)
            urls.append(u)
    return urls


def build_items(
    cat: str,
    urls: list[str],
    limit: int,
    used_md5: set[str],
    used_fhash: set[str],
    *,
    only_hashes: set[str] | None = None,
) -> list[dict]:
    cat_dir = OUT / cat
    wipe_cat(cat_dir)
    items: list[dict] = []
    for u in urls:
        if len(items) >= limit:
            break
        fh = file_hash(u)
        if only_hashes is not None and fh not in only_hashes:
            continue
        if fh in used_fhash:
            continue
        data = get_bytes(u)
        if not data:
            continue
        md = content_md5(data)
        if md in used_md5:
            print("SKIP_DUP_BYTES", cat, fh[:8])
            continue
        used_md5.add(md)
        used_fhash.add(fh)
        item = save_item(cat, len(items) + 1, data, u, cat_dir)
        items.append(item)
        tsize = (cat_dir / f"{item['id']}_t.jpg").stat().st_size
        print("OK", item["id"], tsize // 1024, "KB thumb")
    return items


def dump_review_thumbs(urls: list[str], dest: Path, limit: int = 60) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for p in dest.glob("*"):
        p.unlink()
    n = 0
    meta = []
    seen = set()
    for u in urls:
        fh = file_hash(u)
        if fh in seen:
            continue
        seen.add(fh)
        data = get_bytes(u)
        if not data:
            continue
        thumb = to_jpeg(data, 360, 68)
        name = f"{n+1:02d}_{fh[:10]}.jpg"
        (dest / name).write_bytes(thumb)
        meta.append({"file": name, "hash": fh, "url": u})
        n += 1
        if n >= limit:
            break
    (dest / "index.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REVIEW", dest, n)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    used_md5: set[str] = set()
    used_fhash: set[str] = set()
    manifest: dict = {"categories": []}

    if os.getenv("TRYON_PORTFOLIO_REVIEW") == "1":
        pages = []
        for meta in CATEGORIES.values():
            pages.extend(meta["pages"])
        pages += [
            "https://soco-moscow.ru/uslugi",
            "https://soco-moscow.ru/",
            "https://soco-kras.ru/",
        ]
        dump_review_thumbs(collect_urls(pages), Path("/tmp/soco_curl_review"), 80)
        return

    for cat, meta in CATEGORIES.items():
        urls = collect_urls(meta["pages"])
        items = build_items(cat, urls, int(meta["max"]), used_md5, used_fhash)
        manifest["categories"].append({"id": cat, "title": meta["title"], "items": items})
        print("CAT", cat, len(items))

    curl_pages = [
        "https://soco-moscow.ru/portfoliomenmebversion",
        "https://soco-kras.ru/portfoliomenmebversion",
        "https://soco-moscow.ru/portfoliowomen",
        "https://soco-kras.ru/portfoliowomen",
        "https://soco-moscow.ru/portfoliocolor",
        "https://soco-moscow.ru/uslugi",
        "https://soco-moscow.ru/",
        "https://soco-kras.ru/",
    ]
    curl_urls = collect_urls(curl_pages)
    curl_used_md5: set[str] = set()
    curl_used_fh: set[str] = set()
    if CURL_HASHES:
        curl_items = build_items(
            "curl",
            curl_urls,
            10,
            curl_used_md5,
            curl_used_fh,
            only_hashes=CURL_HASHES,
        )
        for cat in manifest["categories"]:
            before = len(cat["items"])
            cat["items"] = [it for it in cat["items"] if it.get("file_hash") not in curl_used_fh]
            if len(cat["items"]) != before:
                print("MOVED_TO_CURL", cat["id"], before, "->", len(cat["items"]))
    else:
        wipe_cat(OUT / "curl")
        curl_items = []
        print("CURL empty — set TRYON_CURL_HASHES after review")

    manifest["categories"].append({"id": "curl", "title": "Хим. завивка", "items": curl_items})
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", MANIFEST)
    for cat in manifest["categories"]:
        print("FINAL", cat["id"], len(cat["items"]))


if __name__ == "__main__":
    main()
