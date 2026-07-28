#!/usr/bin/env python3
"""
Сравнительный тест Perfect Corp vs AILab для AI-примерки волос.

Использование:
  export PERFECTCORP_API_KEY="..."
  export AILAB_API_KEY="..."
  python3 run_comparison.py --selfie selfie.jpg [--ref hair_ref.jpg]

Perfect Corp: https://yce.perfectcorp.com/ai-api  (бесплатные credits после регистрации)
AILab:       https://www.ailabtools.com/           (пакет от $12 / 2000 credits)

Контекст: docs/soco-salon-ai-tryon-session.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

PERFECT_BASE = "https://yce-api-01.makeupar.com"
AILAB_SUBMIT = "https://www.ailabapi.com/api/portrait/effects/hairstyle-editor-pro"
AILAB_POLL = "https://www.ailabapi.com/api/common/query-async-task-result"


def poll_perfect(task_id: str, api_key: str, timeout: int = 120) -> dict:
    url = f"{PERFECT_BASE}/s2s/v2.1/task/hair-transfer/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status") or data.get("task_status")
        if status in ("success", "SUCCESS", "succeeded", 2):
            return data
        if status in ("error", "ERROR", "failed", 3):
            raise RuntimeError(f"Perfect Corp task failed: {json.dumps(data, ensure_ascii=False)}")
        time.sleep(3)
    raise TimeoutError(f"Perfect Corp task {task_id} timed out")


def test_perfect(selfie: Path, ref: Path | None, out_dir: Path) -> Path | None:
    api_key = os.environ.get("PERFECTCORP_API_KEY", "").strip()
    if not api_key:
        print("[Perfect Corp] SKIP — задайте PERFECTCORP_API_KEY")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload: dict = {}
    if ref and ref.exists():
        payload = {
            "src_file_url": _upload_perfect(selfie, api_key),
            "ref_file_url": _upload_perfect(ref, api_key),
        }
    else:
        payload = {
            "src_file_url": _upload_perfect(selfie, api_key),
            "template_id": "wolf_cut",
        }

    print("[Perfect Corp] Создаю задачу hair-transfer v2.1 …")
    r = requests.post(
        f"{PERFECT_BASE}/s2s/v2.1/task/hair-transfer",
        headers=headers,
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    task = r.json()
    task_id = task.get("task_id") or task.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Unexpected response: {task}")

    print(f"[Perfect Corp] task_id={task_id}, жду результат …")
    result = poll_perfect(task_id, api_key)
    url = _extract_image_url(result)
    if not url:
        out = out_dir / "perfect_raw.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Perfect Corp] URL не найден, сырой ответ: {out}")
        return None

    out = out_dir / "perfect_result.jpg"
    _download(url, out)
    print(f"[Perfect Corp] OK → {out}")
    return out


def _upload_perfect(path: Path, api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.post(
        f"{PERFECT_BASE}/s2s/v2.1/file/hair-transfer",
        headers={**headers, "Content-Type": "application/json"},
        json={"file_name": path.name},
        timeout=30,
    )
    r.raise_for_status()
    meta = r.json()
    upload_url = meta.get("upload_url") or meta.get("data", {}).get("upload_url")
    file_url = meta.get("file_url") or meta.get("data", {}).get("file_url")
    if upload_url:
        with path.open("rb") as f:
            put = requests.put(upload_url, data=f, timeout=60)
            put.raise_for_status()
    if file_url:
        return file_url
    file_id = meta.get("file_id") or meta.get("data", {}).get("file_id")
    if file_id:
        return file_id
    raise RuntimeError(f"Upload response missing url/file_id: {meta}")


def test_ailab(selfie: Path, out_dir: Path, hair_style: str = "LongWavy", color: str = "") -> Path | None:
    api_key = os.environ.get("AILAB_API_KEY", "").strip()
    if not api_key:
        print("[AILab] SKIP — задайте AILAB_API_KEY")
        return None

    headers = {"ailabapi-api-key": api_key}
    data = {
        "task_type": "async",
        "auto": "1",
        "hair_style": hair_style,
        "image_size": "2",
    }
    if color:
        data["color"] = color

    print(f"[AILab] Отправляю {hair_style} …")
    with selfie.open("rb") as f:
        r = requests.post(
            AILAB_SUBMIT,
            headers=headers,
            data=data,
            files={"image": (selfie.name, f, "image/jpeg")},
            timeout=60,
        )
    r.raise_for_status()
    body = r.json()
    if body.get("error_code", 0) != 0:
        raise RuntimeError(f"AILab submit error: {body}")

    task_id = body["task_id"]
    print(f"[AILab] task_id={task_id}, жду …")
    deadline = time.time() + 120
    while time.time() < deadline:
        pr = requests.get(AILAB_POLL, headers=headers, params={"task_id": task_id}, timeout=30)
        pr.raise_for_status()
        res = pr.json()
        if res.get("task_status") == 2:
            images = res.get("data", {}).get("images", [])
            if not images:
                raise RuntimeError(f"No images in response: {res}")
            out = out_dir / "ailab_result.jpg"
            _download(images[0], out)
            print(f"[AILab] OK → {out}")
            return out
        time.sleep(5)
    raise TimeoutError("AILab task timed out")


def _extract_image_url(result: dict) -> str | None:
    for key in ("result_url", "download_url", "url"):
        if result.get(key):
            return result[key]
    data = result.get("data") or result.get("result") or {}
    if isinstance(data, dict):
        for key in ("result_url", "download_url", "url", "image_url"):
            if data.get(key):
                return data[key]
        results = data.get("results") or data.get("images")
        if isinstance(results, list) and results:
            item = results[0]
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return item.get("url") or item.get("result_url")
    return None


def _download(url: str, dest: Path) -> None:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)


def main() -> None:
    p = argparse.ArgumentParser(description="Тест Perfect Corp vs AILab hair try-on")
    p.add_argument("--selfie", type=Path, default=Path("selfie.jpg"))
    p.add_argument("--ref", type=Path, default=None, help="Референс из портфолио (только Perfect Corp)")
    p.add_argument("--out", type=Path, default=Path("results"))
    p.add_argument("--ailab-style", default="LongWavy")
    p.add_argument("--ailab-color", default="")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.selfie.exists():
        print(f"Файл не найден: {args.selfie}", file=sys.stderr)
        sys.exit(1)

    print("=== AI Hair Try-On Comparison ===")
    print(f"Selfie: {args.selfie}")
    if args.ref:
        print(f"Ref:    {args.ref}")
    print()

    results = {}
    try:
        results["perfect"] = test_perfect(args.selfie, args.ref, args.out)
    except Exception as e:
        print(f"[Perfect Corp] ERROR: {e}")

    try:
        results["ailab"] = test_ailab(args.selfie, args.out, args.ailab_style, args.ailab_color)
    except Exception as e:
        print(f"[AILab] ERROR: {e}")

    print()
    print("=== Чеклист качества (оцените вручную) ===")
    checklist = [
        "Лицо сохранилось без «пластиковой» маски?",
        "Линия роста волос выглядит естественно?",
        "Цвет/стрижка похожи на референс из портфолио?",
        "Освещение согласовано с исходным фото?",
        "При повторном запросе результат стабилен?",
    ]
    for i, item in enumerate(checklist, 1):
        print(f"  {i}. {item}")

    if not results.get("perfect") and not results.get("ailab"):
        print()
        print("Нужны API-ключи. Получить бесплатно:")
        print("  Perfect Corp: https://yce.perfectcorp.com/ai-api → Get Free API Key")
        print("  AILab:        https://www.ailabtools.com/ → Developer → API KEY")


if __name__ == "__main__":
    main()
