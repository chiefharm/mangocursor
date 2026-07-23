"""Yandex SpeechKit STT v3 — transcribe Mango MP3 recordings."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple


class YandexSttError(RuntimeError):
    pass


STT_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
OPS_URL = "https://operation.api.cloud.yandex.net/operations"
GET_URL = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"


class YandexSttClient:
    def __init__(self, api_key: str, folder_id: str = "", timeout: int = 120) -> None:
        self.api_key = api_key.strip()
        self.folder_id = folder_id.strip()
        self.timeout = timeout
        if not self.api_key:
            raise YandexSttError("YANDEX_SPEECHKIT_API_KEY is required")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        # For service-account API keys, folder is usually inferred; pass only if set explicitly.
        if self.folder_id and os.getenv("YANDEX_FORCE_FOLDER_ID", "").strip().lower() in ("1", "true", "yes"):
            headers["x-folder-id"] = self.folder_id
        return headers

    def _request_json(self, url: str, payload: Dict[str, Any] | None = None, method: str = "POST") -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YandexSttError(f"HTTP {exc.code} for {url}: {detail}") from exc
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _start_async(self, audio: bytes) -> str:
        body: Dict[str, Any] = {
            "content": base64.b64encode(audio).decode("ascii"),
            "recognitionModel": {
                "model": "general",
                "audioFormat": {"containerAudio": {"containerAudioType": "MP3"}},
                "languageRestriction": {
                    "restrictionType": "WHITELIST",
                    "languageCode": ["ru-RU"],
                },
            },
            "speakerLabeling": {"speakerLabeling": "SPEAKER_LABELING_ENABLED"},
        }
        body["recognitionModel"]["textNormalization"] = {"textNormalization": "TEXT_NORMALIZATION_ENABLED"}

        resp = self._request_json(STT_URL, body)
        op_id = resp.get("id") or resp.get("operationId")
        if not op_id:
            raise YandexSttError(f"No operation id in STT response: {resp}")
        return str(op_id)

    def _wait_operation(self, operation_id: str, poll_interval: float = 3.0, max_wait: int = 600) -> None:
        deadline = time.time() + max_wait
        url = f"{OPS_URL}/{urllib.parse.quote(operation_id)}"
        while time.time() < deadline:
            resp = self._request_json(url, method="GET")
            if resp.get("done"):
                if resp.get("error"):
                    raise YandexSttError(f"STT operation failed: {resp['error']}")
                return
            time.sleep(poll_interval)
        raise YandexSttError(f"Timed out waiting for STT operation {operation_id}")

    def _fetch_recognition(self, operation_id: str) -> List[Dict[str, Any]]:
        url = f"{GET_URL}?operation_id={urllib.parse.quote(operation_id)}"
        req = urllib.request.Request(url, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YandexSttError(f"HTTP {exc.code} getRecognition: {detail}") from exc

        events: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not events and raw.strip().startswith("{"):
            payload = json.loads(raw)
            if isinstance(payload, list):
                events = payload
            elif isinstance(payload, dict):
                events = [payload]
        return events

    @staticmethod
    def _speaker_label(tag: Any) -> str:
        mapping = {0: "Спикер 1", 1: "Спикер 2", 2: "Спикер 3"}
        if tag is None:
            return "Участник"
        if isinstance(tag, str) and tag.isdigit():
            tag = int(tag)
        try:
            return mapping.get(int(tag), f"Спикер {int(tag) + 1}")
        except (TypeError, ValueError):
            return str(tag)

    @staticmethod
    def _pick_speaker(alt: Dict[str, Any]) -> str:
        words = alt.get("words") or []
        speaker_tags = {
            w.get("speakerTag")
            for w in words
            if w.get("speakerTag") is not None and str(w.get("speakerTag")).strip() != ""
        }
        if len(speaker_tags) == 1:
            return YandexSttClient._speaker_label(next(iter(speaker_tags)))
        channel = alt.get("channelTag")
        if channel is not None and str(channel).strip() != "":
            return YandexSttClient._speaker_label(channel)
        return "Участник"

    @staticmethod
    def _format_time_ms(ms: int, call_start_ts: int = 0) -> str:
        if call_start_ts:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("Europe/Moscow")
            dt = datetime.fromtimestamp(call_start_ts + ms / 1000, tz)
            return dt.strftime("%H:%M:%S")
        sec = ms // 1000
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def parse_events(
        self, events: List[Dict[str, Any]], call_start_ts: int = 0
    ) -> List[Tuple[str, str, str]]:
        segments: List[Tuple[str, str, str]] = []
        seen_text: set[str] = set()
        for event in events:
            result = event.get("result") or event
            refinement = result.get("finalRefinement", {}).get("normalizedText")
            final = refinement if isinstance(refinement, dict) else result.get("final")
            if isinstance(final, dict):
                alts = final.get("alternatives") or []
                if alts:
                    alt = alts[0]
                    text = (alt.get("text") or "").strip()
                    words = alt.get("words") or []
                    start_ms = int(words[0].get("startTimeMs", 0)) if words else 0
                    if text:
                        key = text.lower()
                        if key not in seen_text:
                            seen_text.add(key)
                            segments.append(
                                (
                                    self._pick_speaker(alt),
                                    self._format_time_ms(start_ms, call_start_ts),
                                    text,
                                )
                            )
                continue

        if not segments:
            # Fallback: sync-style single blob somewhere in events
            texts: List[str] = []
            for event in events:

                def walk(obj: Any) -> None:
                    if isinstance(obj, dict):
                        if "text" in obj and isinstance(obj["text"], str) and obj["text"].strip():
                            texts.append(obj["text"].strip())
                        for value in obj.values():
                            walk(value)
                    elif isinstance(obj, list):
                        for item in obj:
                            walk(item)

                walk(event)
            if texts:
                segments.append(("Диалог", "", " ".join(dict.fromkeys(texts))))

        return segments

    def transcribe_mp3(self, audio: bytes, call_start_ts: int = 0) -> List[Tuple[str, str, str]]:
        if not audio:
            raise YandexSttError("Empty audio")
        op_id = self._start_async(audio)
        self._wait_operation(op_id)
        events = self._fetch_recognition(op_id)
        segments = self.parse_events(events, call_start_ts)
        if not segments:
            raise YandexSttError(f"Empty STT result for operation {op_id}")
        return segments


def client_from_env() -> YandexSttClient:
    api_key = os.getenv("YANDEX_SPEECHKIT_API_KEY", "").strip()
    folder_id = os.getenv("YANDEX_FOLDER_ID", "").strip()
    return YandexSttClient(api_key, folder_id)
