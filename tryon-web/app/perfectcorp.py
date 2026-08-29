"""Perfect Corp / YouCam hair-transfer client."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any

import httpx

BASE = "https://yce-api-01.makeupar.com"


class PerfectCorpError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class PerfectCorpClient:
    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        key = (api_key or "").strip()
        if not key:
            raise PerfectCorpError("PERFECTCORP_API_KEY is required")
        self.api_key = key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def upload_file(self, path: Path) -> str:
        """Upload local image via File API, return file_id."""
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        if content_type == "image/jpeg":
            content_type = "image/jpg"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            meta_resp = await client.post(
                f"{BASE}/s2s/v2.1/file/hair-transfer",
                headers=self._headers(),
                json={
                    "files": [
                        {
                            "content_type": content_type,
                            "file_name": path.name,
                            "file_size": len(data),
                        }
                    ]
                },
            )
            if meta_resp.status_code >= 400:
                raise PerfectCorpError(
                    f"File API error: {meta_resp.text}",
                    status=meta_resp.status_code,
                    payload=_safe_json(meta_resp),
                )
            meta = meta_resp.json()
            files = meta.get("files") or meta.get("data", {}).get("files") or []
            if not files:
                raise PerfectCorpError(f"Unexpected file API response: {meta}")

            item = files[0]
            file_id = item.get("file_id")
            requests_info = item.get("requests") or []
            if not file_id or not requests_info:
                raise PerfectCorpError(f"Missing upload info: {item}")

            upload = requests_info[0]
            upload_url = upload.get("url")
            method = (upload.get("method") or "PUT").upper()
            upload_headers = dict(upload.get("headers") or {})
            if method != "PUT":
                raise PerfectCorpError(f"Unsupported upload method: {method}")

            put = await client.put(upload_url, content=data, headers=upload_headers)
            if put.status_code >= 400:
                raise PerfectCorpError(
                    f"Upload failed: {put.status_code} {put.text[:300]}",
                    status=put.status_code,
                )
            return file_id

    async def create_hair_transfer(
        self,
        *,
        src_file_id: str | None = None,
        ref_file_id: str | None = None,
        src_file_url: str | None = None,
        ref_file_url: str | None = None,
    ) -> str:
        payload: dict[str, str] = {}
        if src_file_id:
            payload["src_file_id"] = src_file_id
        elif src_file_url:
            payload["src_file_url"] = src_file_url
        else:
            raise PerfectCorpError("src_file_id or src_file_url required")

        if ref_file_id:
            payload["ref_file_id"] = ref_file_id
        elif ref_file_url:
            payload["ref_file_url"] = ref_file_url
        else:
            raise PerfectCorpError("ref_file_id or ref_file_url required")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{BASE}/s2s/v2.1/task/hair-transfer",
                headers=self._headers(),
                json=payload,
            )
            body = _safe_json(resp)
            if resp.status_code >= 400:
                err = body.get("error") or resp.text
                code = body.get("error_code") or ""
                raise PerfectCorpError(
                    f"{err} ({code})".strip(),
                    status=resp.status_code,
                    payload=body,
                )
            task_id = (
                body.get("task_id")
                or body.get("data", {}).get("task_id")
                or (body.get("data") or {}).get("taskId")
            )
            if not task_id:
                raise PerfectCorpError(f"No task_id in response: {body}")
            return task_id

    async def wait_result(self, task_id: str, *, timeout: float = 180.0) -> str:
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while asyncio.get_event_loop().time() < deadline:
                resp = await client.get(
                    f"{BASE}/s2s/v2.1/task/hair-transfer/{task_id}",
                    headers=self._headers(),
                )
                body = _safe_json(resp)
                if resp.status_code >= 400:
                    raise PerfectCorpError(
                        f"Poll error: {resp.text}",
                        status=resp.status_code,
                        payload=body,
                    )
                data = body.get("data") or body
                status = str(data.get("task_status") or data.get("status") or "").lower()
                url = _extract_result_url(data) or _extract_result_url(body)
                if status in {"success", "succeeded", "ok", "done"} or (
                    url and status not in {"error", "failed"}
                ):
                    if not url:
                        raise PerfectCorpError(f"Success without URL: {body}")
                    return url
                if status in {"error", "failed"}:
                    msg = data.get("error_message") or data.get("error") or "task failed"
                    raise PerfectCorpError(str(msg), payload=body)
                await asyncio.sleep(3)
        raise PerfectCorpError(f"Task timed out: {task_id}")


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return {"raw": resp.text}


def _extract_result_url(data: dict) -> str | None:
    for key in (
        "result_url",
        "download_url",
        "url",
        "image_url",
        "file_url",
        "output_url",
        "result",
    ):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    results = data.get("results") or data.get("images") or data.get("output") or []
    if isinstance(results, dict):
        return _extract_result_url(results)
    if isinstance(results, list) and results:
        item = results[0]
        if isinstance(item, str) and item.startswith("http"):
            return item
        if isinstance(item, dict):
            found = _extract_result_url(item)
            if found:
                return found
    # last resort: scan nested values for an https image URL
    return _find_http_url(data)


def _find_http_url(obj: Any) -> str | None:
    if isinstance(obj, str) and obj.startswith("http") and any(
        ext in obj.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", "amazonaws.com", "makeupar")
    ):
        return obj
    if isinstance(obj, dict):
        for val in obj.values():
            found = _find_http_url(val)
            if found:
                return found
    if isinstance(obj, list):
        for val in obj:
            found = _find_http_url(val)
            if found:
                return found
    return None
