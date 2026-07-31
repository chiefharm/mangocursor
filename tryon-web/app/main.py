"""SOCO AI hair try-on web service (Perfect Corp / YouCam)."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .perfectcorp import PerfectCorpClient, PerfectCorpError

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("TRYON_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

MAX_REFS = 3
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

app = FastAPI(title="SOCO AI Try-On", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _client() -> PerfectCorpClient:
    key = os.getenv("PERFECTCORP_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=500, detail="PERFECTCORP_API_KEY is not configured")
    return PerfectCorpClient(key)


async def _save_upload(file: UploadFile, dest: Path) -> None:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="File too large (max 8MB)")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict:
    has_key = bool(os.getenv("PERFECTCORP_API_KEY", "").strip())
    return {"ok": True, "perfectcorp_configured": has_key}


@app.post("/api/tryon")
async def tryon(
    before: UploadFile = File(..., description="Client selfie / before photo"),
    refs: list[UploadFile] = File(..., description="Up to 3 reference hairstyle photos"),
) -> JSONResponse:
    if not refs:
        raise HTTPException(status_code=400, detail="Upload at least 1 reference photo")
    if len(refs) > MAX_REFS:
        raise HTTPException(status_code=400, detail=f"Max {MAX_REFS} reference photos")

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    result_job_dir = RESULT_DIR / job_id
    result_job_dir.mkdir(parents=True, exist_ok=True)

    before_path = job_dir / f"before{Path(before.filename or 'before.jpg').suffix or '.jpg'}"
    await _save_upload(before, before_path)

    ref_paths: list[Path] = []
    for i, ref in enumerate(refs, 1):
        suffix = Path(ref.filename or f"ref{i}.jpg").suffix or ".jpg"
        path = job_dir / f"ref_{i}{suffix}"
        await _save_upload(ref, path)
        ref_paths.append(path)

    client = _client()

    try:
        src_file_id = await client.upload_file(before_path)
        ref_ids = await asyncio.gather(*[client.upload_file(p) for p in ref_paths])

        async def one(i: int, ref_id: str) -> dict:
            try:
                task_id = await client.create_hair_transfer(
                    src_file_id=src_file_id,
                    ref_file_id=ref_id,
                )
                url = await client.wait_result(task_id)
                # download result locally so UI doesn't depend on Perfect Corp TTL
                async with httpx.AsyncClient(timeout=60) as http:
                    img = await http.get(url)
                    img.raise_for_status()
                    out = result_job_dir / f"after_{i}.jpg"
                    out.write_bytes(img.content)
                return {
                    "index": i,
                    "status": "ok",
                    "result_url": f"/api/results/{job_id}/after_{i}.jpg",
                    "task_id": task_id,
                }
            except PerfectCorpError as exc:
                return {
                    "index": i,
                    "status": "error",
                    "error": str(exc),
                }

        results = await asyncio.gather(*[one(i, rid) for i, rid in enumerate(ref_ids, 1)])
    except PerfectCorpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Try-on failed: {exc}") from exc

    return JSONResponse(
        {
            "job_id": job_id,
            "before_url": f"/api/uploads/{job_id}/{before_path.name}",
            "results": results,
        }
    )


@app.get("/api/uploads/{job_id}/{filename}")
async def get_upload(job_id: str, filename: str) -> FileResponse:
    path = UPLOAD_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.get("/api/results/{job_id}/{filename}")
async def get_result(job_id: str, filename: str) -> FileResponse:
    path = RESULT_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@app.post("/api/cleanup")
async def cleanup(job_id: str = Form(...)) -> dict:
    """Optional: delete temporary job files after user finishes."""
    for root in (UPLOAD_DIR / job_id, RESULT_DIR / job_id):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    return {"ok": True}
