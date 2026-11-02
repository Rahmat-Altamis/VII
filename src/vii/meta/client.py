"""Meta Model API client via OpenAI SDK (Responses API compatibility).

Primary endpoint: META_BASE_URL (default https://api.meta.ai/v1).
Secrets are redacted in all logs. Bounded retries + explicit timeouts.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from vii.errors import ProviderConfigurationError, ProviderError

log = logging.getLogger("vii.meta")


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if "key" in k.lower() or "token" in k.lower() else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 40 and "sk-" in obj:
        return "***"
    return obj


class MetaClient:
    def __init__(self, api_key: str, base_url: str, model: str,
                 timeout_s: float = 120.0, max_retries: int = 2,
                 transcription_model: str = "muse-voice-transcribe-1.0"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transcription_model = transcription_model
        self._client = None

    @property
    def live(self) -> bool:
        return bool(self.api_key.strip())

    def _sdk(self):
        if not self.api_key.strip():
            raise ProviderConfigurationError(
                "MODEL_API_KEY is not configured: provider-backed analysis is "
                "unavailable. Set MODEL_API_KEY, or explicitly opt into "
                "synthetic demo mode (VII_DEMO_MODE=true).")
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                  timeout=self.timeout_s, max_retries=self.max_retries)
        return self._client

    # -- Files API ---------------------------------------------------------
    def upload_video(self, path: str, purpose: str = "user_data") -> dict:
        """Upload via Meta Files API; returns {'file_id': ...}."""
        log.info("files.upload path=%s purpose=%s", path, purpose)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with open(path, "rb") as f:
                    resp = self._sdk().files.create(file=f, purpose=purpose)
                fid = getattr(resp, "id", None) or (resp.get("id") if isinstance(resp, dict) else None)
                if not fid:
                    raise ProviderError(f"Files API returned no file id: {str(resp)[:300]}")
                log.info("files.upload ok file_id=%s", fid)
                return {"file_id": fid}
            except Exception as e:
                last = e
                log.warning("files.upload attempt %d failed: %s", attempt, str(e)[:300])
                time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"Files API upload failed after retries: {last}")

    # -- Responses API ------------------------------------------------------
    def responses_create(self, payload: dict) -> dict:
        """POST a Responses API request; returns parsed JSON dict."""
        log.info("responses.create model=%s keys=%s",
                 payload.get("model"), sorted(_redact(payload).keys()))
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._sdk().responses.create(**payload)
                data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
                log.info("responses.create ok id=%s", data.get("id"))
                return data
            except Exception as e:
                last = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                log.warning("responses.create attempt %d failed (%s): %s",
                            attempt, status, str(e)[:300])
                if status == 429:
                    time.sleep(4 * (attempt + 1))
                    continue
                time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"Responses API failed after retries: {last}")

    # -- Transcription -------------------------------------------------------
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        """Muse Voice Transcribe; returns normalized dict."""
        log.info("transcribe model=%s path=%s", self.transcription_model, audio_path)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {"model": self.transcription_model}
                with open(audio_path, "rb") as f:
                    kwargs["file"] = f
                    if language:
                        kwargs["language"] = language
                    resp = self._sdk().audio.transcriptions.create(**kwargs)
                if hasattr(resp, "model_dump"):
                    return resp.model_dump()
                if isinstance(resp, dict):
                    return resp
                return {"text": getattr(resp, "text", str(resp))}
            except Exception as e:
                last = e
                log.warning("transcribe attempt %d failed: %s", attempt, str(e)[:300])
                time.sleep(1.5 * (attempt + 1))
        raise ProviderError(f"Transcription failed after retries: {last}")

    def redact(self, payload: dict) -> dict:
        return _redact(payload)
