"""Provider seams: usage accounting, error classification, visual perception.

All provider behaviour here is local/mocked — no live calls, no credits.
SAM 3.1 and Muse live contracts remain unverified; these tests assert the
honest blocked/unknown states, not fabricated success.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from vii.config import Settings
from vii.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderPermissionError,
    ProviderRateLimitError,
)
from vii.meta.client import _classify_error, provider_usage
from vii.providers.capabilities import provider_capabilities
from vii.providers.visual import (
    VisualPerceptionUnavailableError,
    get_visual_perception_provider,
)


def _settings(**kw) -> Settings:
    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("MODEL_API_KEY", "")
    kw.setdefault("VII_DEMO_MODE", False)
    # Isolate from any operator keyring fallback under the repo's data dir:
    # an empty env key must mean "no key" in these tests.
    kw.setdefault("VII_STORAGE_DIR", "/tmp/vii-provider-seam-tests-no-keyring")
    return Settings(_env_file=None, **kw)


class _HttpError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = SimpleNamespace(status_code=status)


def test_provider_usage_reported_only_when_provider_returns_it():
    reported = provider_usage({"id": "resp_1", "usage": {
        "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}})
    assert reported["usage_status"] == "reported"
    assert reported["total_tokens"] == 15
    assert reported["estimated_cost_usd"] is None  # pricing unverified

    unknown = provider_usage({"id": "resp_2"})
    assert unknown["usage_status"] == "unknown"
    assert unknown["request_id"] == "resp_2"
    assert "total_tokens" not in unknown  # never invented


def test_error_classification_and_retry_flags():
    assert isinstance(_classify_error(_HttpError(403)), ProviderPermissionError)
    assert isinstance(_classify_error(_HttpError(401)), ProviderPermissionError)
    assert isinstance(_classify_error(_HttpError(429)), ProviderRateLimitError)
    assert ProviderRateLimitError.retryable is True
    assert ProviderPermissionError.retryable is False
    assert ProviderError.retryable is False
    # Worker treats configuration errors as terminal (ValueError family).
    assert issubclass(ProviderConfigurationError, ValueError)


def test_visual_perception_sam_selection_states():
    provider = get_visual_perception_provider(_settings())
    assert provider.capabilities()["status"] == "blocked"
    with pytest.raises(VisualPerceptionUnavailableError):
        provider.perceive_video("clip.mp4")

    # SAM selected but no key anywhere: still blocked, honest reason.
    no_key = get_visual_perception_provider(_settings(
        VII_ENABLE_VISUAL_PERCEPTION=True,
        VII_VISUAL_PERCEPTION_PROVIDER="sam"))
    assert no_key.capabilities()["status"] == "blocked"
    with pytest.raises(VisualPerceptionUnavailableError, match="no API key"):
        no_key.perceive_video("clip.mp4")

    # Key configured: the docs-verified SAM 3.1 adapter is selected.
    # Live acceptance stays unverified, and a request is never sent
    # without a concept prompt.
    configured = get_visual_perception_provider(_settings(
        VII_ENABLE_VISUAL_PERCEPTION=True,
        VII_VISUAL_PERCEPTION_PROVIDER="sam",
        VII_SAM_API_KEY="test-key-not-real"))
    assert configured.name == "sam"
    assert configured.model == "sam-3.1"
    caps = configured.capabilities()
    assert caps["status"] == "configured_unverified"
    assert caps["supports_tracking"] is True
    with pytest.raises(VisualPerceptionUnavailableError, match="concept prompt"):
        configured.perceive_video("clip.mp4")


def test_capability_report_states_are_explicit():
    caps = provider_capabilities(_settings())
    assert caps["visual_perception"]["status"] == "blocked"
    assert caps["ffmpeg"]["status"] == "optional"
    assert caps["evidence_search"]["status"] == "unavailable_no_provider"
    assert caps["video_understanding"]["status"] in ("blocked", "demo_opt_in")


def test_transcription_gate_skips_audio_extraction(tmp_path):
    """With VII_ENABLE_TRANSCRIPTION=false, no FFmpeg extraction is attempted
    (a missing media file would otherwise surface an ffmpeg error engine)."""
    from vii.application.pipeline import Pipeline

    pipe = object.__new__(Pipeline)
    pipe.settings = _settings(VII_ENABLE_TRANSCRIPTION=False)
    logs: list = []
    jobs = SimpleNamespace(log=lambda *a: logs.append(a))
    tr = pipe._transcribe("job_x", str(tmp_path / "missing.mp4"), False,
                          SimpleNamespace(), jobs)
    assert tr.engine == "transcription-disabled-by-config"
    assert tr.segments == []
    assert logs  # the skip is logged, never silent
