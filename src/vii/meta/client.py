"""Meta Model API client via OpenAI SDK (Responses API compatibility).

Primary endpoint: META_BASE_URL (default https://api.meta.ai/v1).
Secrets are redacted in all logs. Bounded retries + explicit timeouts.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from vii.errors import (
    MalformedProviderResponseError,
    ProviderConfigurationError,
    ProviderError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

log = logging.getLogger("vii.meta")


def provider_usage(resp: dict) -> dict:
    """Normalize provider-reported usage; never invent numbers.

    Returns usage_status="reported" with token counts only when the
    provider actually returned a usage object, else "unknown".
    Cost stays unknown until pricing is verified against official docs.
    """
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        return {"request_id": (resp.get("id", "") if isinstance(resp, dict) else ""),
                "usage_status": "unknown", "estimated_cost_usd": None,
                "cost_status": "unknown_pricing_unverified"}
    return {"request_id": resp.get("id", ""), "usage_status": "reported",
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "estimated_cost_usd": None,
            "cost_status": "unknown_pricing_unverified"}


# Client errors that re-sending the identical request cannot fix.
NON_RETRYABLE_STATUSES = frozenset({400, 401, 403, 404, 406, 413})


def _status_of(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


class _HttpStatusError(Exception):
    """HTTP error from a direct httpx call (carries its status)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.response = type("R", (), {"status_code": status})()
        super().__init__(f"HTTP {status}: {body[:300]}")


def _resp_text(resp) -> str:
    try:
        return str(getattr(resp, "text", "") or "")
    except Exception:
        return ""


def _safe(exc: Exception) -> str:
    from vii.logging_setup import redact

    return redact(str(exc))[:300]


def _classify_error(exc: Exception) -> ProviderError:
    """Map a transport exception to a typed provider error (no secrets)."""
    from vii.logging_setup import redact

    detail = redact(str(exc))
    status = _status_of(exc)
    if status in (401, 403):
        return ProviderPermissionError(f"provider permission denied (HTTP {status})")
    if status == 429:
        return ProviderRateLimitError("provider rate limited (HTTP 429)")
    if "timeout" in type(exc).__name__.lower() or "timed out" in detail.lower():
        return ProviderTimeoutError(f"provider request timed out: {detail[:200]}")
    return ProviderError(f"provider request failed: {detail[:300]}")


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
        self._upload_cache: dict[str, str] = {}

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
            # Single retry layer: the SDK must not retry on its own; the
            # bounded loops in this class are the only retries.
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                  timeout=self.timeout_s, max_retries=0)
        return self._client

    # -- Files API ---------------------------------------------------------
    def upload_video(self, path: str, purpose: str = "user_data") -> dict:
        """Upload via Meta Files API; returns {'file_id': ...}.

        Identical content is uploaded at most once per client: a retry
        (here or at the worker layer) reuses the cached file_id instead
        of re-uploading and re-billing the same bytes.
        """
        log.info("files.upload path=%s purpose=%s", path, purpose)
        cache_key = None
        try:
            from vii.media.hashing import sha256_file
            cache_key = f"{purpose}:{sha256_file(path)}"
        except Exception:
            cache_key = None
        if cache_key and cache_key in self._upload_cache:
            return {"file_id": self._upload_cache[cache_key]}
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with open(path, "rb") as f:
                    resp = self._sdk().files.create(file=f, purpose=purpose)
                fid = getattr(resp, "id", None) or (resp.get("id") if isinstance(resp, dict) else None)
                if not fid:
                    raise ProviderError(f"Files API returned no file id: {str(resp)[:300]}")
                log.info("files.upload ok file_id=%s", fid)
                if cache_key:
                    self._upload_cache[cache_key] = fid
                return {"file_id": fid}
            except Exception as e:
                last = e
                log.warning("files.upload attempt %d failed: %s", attempt, str(e)[:300])
                if _status_of(e) in NON_RETRYABLE_STATUSES:
                    break  # identical re-upload cannot fix a client error
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise _classify_error(last) if last is not None else ProviderError(
            "Files API upload failed")

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
                status = _status_of(e)
                log.warning("responses.create attempt %d failed (%s): %s",
                            attempt, status, str(e)[:300])
                if status in NON_RETRYABLE_STATUSES:
                    break  # identical request cannot fix a client error
                if attempt < self.max_retries:
                    time.sleep(4 * (attempt + 1) if status == 429
                               else 1.5 * (attempt + 1))
        raise _classify_error(last) if last is not None else ProviderError(
            "Responses API failed")

    # -- Transcription -------------------------------------------------------
    def transcribe_url(self) -> str:
        """Documented ASR endpoint; base already includes /v1."""
        return f"{self.base_url.rstrip('/')}/asr/transcribe"

    def transcribe(self, audio_path: str, language: str | None = None,
                 mode: str = "DIARIZATION", _post=None) -> dict:
        """Muse Voice Transcribe via POST {base}/asr/transcribe.

        Multipart: ``request`` (JSON ``{model, audioEncoding, mode}``,
        content type ``application/json``) + ``audio`` (WAV bytes,
        content type ``audio/wav``). Returns the documented JSON body
        plus a ``text`` alias of the complete transcript. DIARIZATION
        is the default: VII segments carry timestamps and speaker
        attribution, which is what speaker labels exist for;
        ENDPOINTING drops speakers and PUSH_TO_TALK drops turns.
        ``_post`` is a test seam for the httpx call.
        """
        import json as _json
        import uuid as _uuid

        if not self.api_key.strip():
            raise ProviderConfigurationError(
                "MODEL_API_KEY is not configured: provider-backed analysis is "
                "unavailable. Set MODEL_API_KEY, or explicitly opt into "
                "synthetic demo mode (VII_DEMO_MODE=true).")
        if _post is None:
            import httpx

            _post = httpx.post
        payload = {"model": self.transcription_model, "audioEncoding": "WAV",
                   "mode": mode}
        if language:
            payload["languageBias"] = language
        session_id = _uuid.uuid4().hex[:16]
        log.info("transcribe model=%s mode=%s path=%s session=%s",
                 self.transcription_model, mode, audio_path, session_id)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()
                resp = _post(
                    self.transcribe_url(), params={"sessionId": session_id},
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Accept": "application/json"},
                    files={"request": (None, _json.dumps(payload),
                                       "application/json"),
                           "audio": ("audio.wav", audio_bytes, "audio/wav")},
                    timeout=self.timeout_s)
                status = getattr(resp, "status_code", 0) or 0
                if status >= 400:
                    raise _HttpStatusError(status, _resp_text(resp))
                body = resp.json() if hasattr(resp, "json") else {}
                if not isinstance(body, dict):
                    raise MalformedProviderResponseError(
                        "transcription response was not a JSON object")
                body["text"] = body.get("transcript", "")
                return body
            except Exception as e:
                last = e
                log.warning("transcribe attempt %d failed: %s", attempt, _safe(e))
                status = (_status_of(e) if not isinstance(e, _HttpStatusError)
                          else e.status)
                if status in NON_RETRYABLE_STATUSES:
                    break
                if attempt < self.max_retries:
                    time.sleep(2 * (attempt + 1) if status == 429
                               else 1.5 * (attempt + 1))
        raise _classify_error(last) if last is not None else ProviderError(
            "Transcription failed")

    def redact(self, payload: dict) -> dict:
        return _redact(payload)
