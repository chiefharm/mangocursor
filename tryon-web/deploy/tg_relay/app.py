"""Telegram Bot API relay for RU → EU.

NSK (Timeweb) cannot reach api.telegram.org. This service runs on Amsterdam
and proxies Bot API calls. Webhooks still hit primerka (NSK inbound is fine).
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

TG_BASE = "https://api.telegram.org"
RELAY_SECRET = os.getenv("TRYON_TG_RELAY_SECRET", "").strip() or "soco-tg-relay"
BOT_TOKEN = (
    os.getenv("TRYON_TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
)

app = FastAPI(title="SOCO Telegram Relay", version="1.0.0")


def _check_secret(secret: Optional[str]) -> None:
    if not RELAY_SECRET:
        return
    if (secret or "").strip() != RELAY_SECRET:
        raise HTTPException(status_code=403, detail="bad relay secret")


def _token() -> str:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN missing on relay")
    return BOT_TOKEN


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "telegram_token": bool(BOT_TOKEN)}


@app.api_route("/bot/{method}", methods=["GET", "POST"])
async def proxy_bot(
    method: str,
    request: Request,
    x_relay_secret: Optional[str] = Header(default=None),
) -> Response:
    """Proxy JSON/form Bot API methods: sendMessage, setWebhook, getMe, …"""
    _check_secret(x_relay_secret)
    method = method.strip().lstrip("/")
    if not method or "/" in method or ".." in method:
        raise HTTPException(status_code=400, detail="bad method")

    url = f"{TG_BASE}/bot{_token()}/{method}"
    body = await request.body()
    headers = {}
    ctype = request.headers.get("content-type")
    if ctype:
        headers["Content-Type"] = ctype

    async with httpx.AsyncClient(timeout=120.0) as client:
        if request.method == "GET":
            resp = await client.get(url, params=dict(request.query_params))
        else:
            resp = await client.post(url, content=body, headers=headers)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({"service": "soco-tg-relay", "ok": True})
