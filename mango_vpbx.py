"""Mango Office VPBX API client (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


BASE_URL = "https://app.mango-office.ru/vpbx"
DEFAULT_STATS_FIELDS = (
    "records,start,finish,answer,from_extension,from_number,"
    "to_extension,to_number,line_number,entry_id"
)


class MangoVpbxError(RuntimeError):
    pass


@dataclass
class CallRecord:
    entry_id: str
    start: int
    finish: int
    answer: int
    from_extension: str
    from_number: str
    to_extension: str
    to_number: str
    line_number: str
    recording_ids: List[str]
    raw: Dict[str, Any]

    @property
    def duration_sec(self) -> int:
        if self.finish and self.start:
            return max(self.finish - self.start, 0)
        return 0

    @property
    def client_number(self) -> str:
        for value in (self.from_number, self.to_number):
            digits = re.sub(r"\D", "", value or "")
            if len(digits) >= 10:
                return digits
        return self.from_number or self.to_number or "unknown"

    @property
    def employee_label(self) -> str:
        for value in (self.to_extension, self.from_extension):
            if value and not re.fullmatch(r"\d+", value):
                return value
        return self.to_extension or self.from_extension or "сотрудник"


class MangoVpbxClient:
    def __init__(self, api_key: str, api_salt: str, timeout: int = 60) -> None:
        self.api_key = api_key.strip()
        self.api_salt = api_salt.strip()
        self.timeout = timeout
        if not self.api_key or not self.api_salt:
            raise MangoVpbxError("MANGO_VPBX_API_KEY and MANGO_VPBX_API_SALT are required")

    def _sign(self, payload: str) -> str:
        return hashlib.sha256(f"{self.api_key}{payload}{self.api_salt}".encode()).hexdigest()

    def _post(self, path: str, data: Dict[str, Any]) -> Any:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        form = urllib.parse.urlencode(
            {
                "vpbx_api_key": self.api_key,
                "sign": self._sign(payload),
                "json": payload,
            }
        ).encode("utf-8")
        url = f"{BASE_URL}/{path.lstrip('/')}"
        retries = (10, 30, 60, 120)
        last_exc: MangoVpbxError | None = None
        body = b""
        for attempt in range(len(retries) + 1):
            req = urllib.request.Request(url, data=form, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                last_exc = None
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_exc = MangoVpbxError(f"HTTP {exc.code} for {path}: {detail}")
                if exc.code == 429 and attempt < len(retries):
                    wait = retries[attempt]
                    print(f"[WARN] Mango rate limit on {path}, retry in {wait}s…")
                    time.sleep(wait)
                    continue
                raise last_exc from exc
        if last_exc is not None:
            raise last_exc

        text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def request_stats(
        self,
        date_from: int,
        date_to: int,
        *,
        fields: Optional[str] = None,
        incoming: Optional[bool] = None,
        outgoing: Optional[bool] = None,
        success: Optional[bool] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "date_from": str(date_from),
            "date_to": str(date_to),
            "fields": fields or DEFAULT_STATS_FIELDS,
        }
        if incoming is not None:
            payload["incoming"] = incoming
        if outgoing is not None:
            payload["outgoing"] = outgoing
        if success is not None:
            payload["success"] = success
        return self._post("stats/request", payload)

    def get_stats_result(self, key: str) -> str:
        result = self._post("stats/result", {"key": key})
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "data" in result and isinstance(result["data"], list):
                return self._rows_to_csv(result["data"])
            if result.get("status") == "work":
                raise MangoVpbxError("stats/result still processing")
            raise MangoVpbxError(f"Unexpected stats/result payload: {result}")
        return str(result)

    def fetch_stats(
        self,
        date_from: int,
        date_to: int,
        *,
        poll_interval: float = 2.0,
        max_attempts: int = 30,
        **filters: Any,
    ) -> List[CallRecord]:
        request = self.request_stats(date_from, date_to, **filters)
        if not isinstance(request, dict):
            raise MangoVpbxError(f"Unexpected stats/request response: {request}")
        key = request.get("key")
        if not key:
            raise MangoVpbxError(f"stats/request failed: {request}")

        csv_text = ""
        for _ in range(max_attempts):
            try:
                csv_text = self.get_stats_result(key)
                break
            except MangoVpbxError as exc:
                if "still processing" not in str(exc):
                    raise
                time.sleep(poll_interval)
        else:
            raise MangoVpbxError("Timed out waiting for stats/result")

        return self.parse_stats_csv(csv_text, filters.get("fields", DEFAULT_STATS_FIELDS))

    @staticmethod
    def parse_stats_csv(csv_text: str, fields: str = DEFAULT_STATS_FIELDS) -> List[CallRecord]:
        lines = [line.strip() for line in csv_text.splitlines() if line.strip()]
        if not lines:
            return []

        field_names = [part.strip() for part in fields.split(",")]
        first_parts = [part.strip() for part in lines[0].split(";")]
        if first_parts and first_parts[0] in field_names:
            header = first_parts
            data_lines = lines[1:]
        else:
            header = field_names
            data_lines = lines

        records: List[CallRecord] = []
        for line in data_lines:
            values = [part.strip() for part in line.split(";")]
            if len(values) < len(header):
                values.extend([""] * (len(header) - len(values)))
            row = dict(zip(header, values))
            recording_raw = row.get("records", "")
            recording_ids = [
                item.strip()
                for item in recording_raw.split(",")
                if item.strip() and item.strip() not in ("[]", "[[]]")
            ]
            try:
                start = int(row.get("start") or 0)
                finish = int(row.get("finish") or 0)
                answer = int(row.get("answer") or 0)
            except ValueError:
                start = finish = answer = 0
            entry_id = row.get("entry_id") or ""
            if not entry_id:
                continue
            records.append(
                CallRecord(
                    entry_id=entry_id,
                    start=start,
                    finish=finish,
                    answer=answer,
                    from_extension=row.get("from_extension", ""),
                    from_number=row.get("from_number", ""),
                    to_extension=row.get("to_extension", ""),
                    to_number=row.get("to_number", ""),
                    line_number=row.get("line_number", ""),
                    recording_ids=recording_ids,
                    raw=row,
                )
            )
        return records

    @staticmethod
    def _rows_to_csv(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return ""
        header = list(rows[0].keys())
        lines = [";".join(header)]
        for row in rows:
            lines.append(";".join(str(row.get(col, "")) for col in header))
        return "\n".join(lines)

    @staticmethod
    def normalize_recording_id(raw: str) -> str:
        if not raw or raw.strip() in ("[]", "[[]]"):
            return ""
        match = re.search(r"\[([^\]]+)\]", raw or "")
        if match:
            inner = match.group(1)
            if inner.strip() in ("", "[]"):
                return ""
            return inner
        cleaned = (raw or "").strip().strip("[]")
        return "" if cleaned in ("", "[]") else cleaned

    def download_recording(self, recording_id: str) -> bytes:
        recording_id = self.normalize_recording_id(recording_id)
        payload = json.dumps({"recording_id": recording_id, "action": "download"}, separators=(",", ":"))
        form = urllib.parse.urlencode(
            {
                "vpbx_api_key": self.api_key,
                "sign": self._sign(payload),
                "json": payload,
            }
        ).encode("utf-8")
        url = f"{BASE_URL}/queries/recording/post"
        req = urllib.request.Request(url, data=form, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read()
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MangoVpbxError(f"HTTP {exc.code} downloading recording: {detail}") from exc
        if body[:1] == b"{" or "json" in content_type:
            raise MangoVpbxError(f"Unexpected recording response: {body[:200]!r}")
        return body

    def get_recording_link(self, recording_id: str, action: str = "download") -> str:
        response = self._post(
            "queries/recording/post",
            {"recording_id": recording_id, "action": action},
        )
        if isinstance(response, dict):
            for key in ("recording_link", "link", "url"):
                if response.get(key):
                    return str(response[key])
        if isinstance(response, str):
            match = re.search(r"https?://\S+", response)
            if match:
                return match.group(0)
            if response.startswith("location:"):
                return response.split(":", 1)[1].strip()
        raise MangoVpbxError(f"Could not parse recording link for {recording_id}: {response}")
