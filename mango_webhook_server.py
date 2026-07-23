#!/usr/bin/env python3
"""Minimal HTTP server for Mango webhooks (stores JSON payloads by entry_id)."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs


def extract_entry_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("entry_id", "entryId", "call_id", "callId"):
        value = payload.get(key)
        if value:
            return str(value)
    call = payload.get("call")
    if isinstance(call, dict):
        for key in ("entry_id", "entryId", "id"):
            if call.get(key):
                return str(call[key])
    return None


def normalize_payload(raw: bytes, content_type: str) -> Dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    if "application/json" in content_type:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"payload": data}
    if "application/x-www-form-urlencoded" in content_type or "=" in text:
        parsed = parse_qs(text, keep_blank_values=True)
        flat = {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
        if "json" in flat and isinstance(flat["json"], str):
            try:
                nested = json.loads(flat["json"])
                if isinstance(nested, dict):
                    flat.update(nested)
            except json.JSONDecodeError:
                pass
        return flat
    return {"raw": text}


class MangoWebhookHandler(BaseHTTPRequestHandler):
    store_dir: Path = Path("data/webhooks")
    auth_token: str = ""

    def _authorized(self) -> bool:
        if not self.auth_token:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {self.auth_token}":
            return True
        query = parse_qs(self.path.split("?", 1)[-1])
        token = query.get("token", [""])[0]
        return token == self.auth_token

    def _save(self, payload: Dict[str, Any]) -> None:
        entry_id = extract_entry_id(payload)
        if not entry_id:
            entry_id = re.sub(r"[^\w.-]+", "_", str(payload.get("recording_id", "unknown")))
        self.store_dir.mkdir(parents=True, exist_ok=True)
        out = self.store_dir / f"{entry_id}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        try:
            payload = normalize_payload(raw, content_type)
            self._save(payload)
        except Exception as exc:  # noqa: BLE001
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        print(f"[WEBHOOK] {self.address_string()} - {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mango webhook receiver")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--store-dir", default="data/webhooks")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    handler = MangoWebhookHandler
    handler.store_dir = Path(args.store_dir)
    handler.auth_token = args.token

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"[WEBHOOK] Listening on http://{args.host}:{args.port}")
    print(f"[WEBHOOK] Store dir: {handler.store_dir.resolve()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
