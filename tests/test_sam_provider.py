"""SAM 3.1 adapter: wire-grammar parser, provider, pipeline demo guard.

Fake transport only — no live calls, no credits. Wire samples follow the
documented grammar (Meta SAM 3.1 docs): one line per frame,
``<Nf>id<|box;...|><|mask;...;data=H,W,ENC PAYLOAD|>``, stable object
ids across frames, empty output_text = zero matches (valid outcome).
"""
from __future__ import annotations

import pytest

WIRE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.91|>"
    "<|mask;x=0;y=0;c=0.91;data=27,60,!abc,def|>,"
    "2<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,48,~xyz|>\n"
    "<2f>0<|box;x1=215;y1=230;x2=272;y2=256;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,60,!qqq|>"
)


class _FakeClient:
    """MetaClient-shaped fake: records payloads, returns canned dicts."""

    live = True

    def __init__(self, text=WIRE):
        self.text = text
        self.payloads: list[dict] = []
        self.uploads: list[str] = []

    def responses_create(self, payload):
        self.payloads.append(payload)
        return {"id": "resp_test", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": self.text}]}]}

    def upload_video(self, path, purpose="user_data"):
        self.uploads.append(path)
        return {"file_id": "file-123"}


def _settings(tmp_path, **kw):
    from vii.config import Settings

    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("MODEL_API_KEY", "")
    kw.setdefault("VII_STORAGE_DIR", tmp_path)
    return Settings(_env_file=None, **kw)


# -- parser -----------------------------------------------------------------

def test_parse_sam_output_records_and_mask_artifacts(tmp_path):
    from vii.providers.visual import parse_sam_output

    obs = parse_sam_output(WIRE, asset_id="asset-1", prompt="red bicycle",
                           mask_dir=tmp_path, request_id="resp_test")
    assert [o.frame_index for o in obs] == [0, 0, 2]  # sparse frames kept
    assert [o.object_id for o in obs] == ["0", "2", "0"]  # stable track ids
    first = obs[0]
    assert first.provider == "sam" and first.model == "sam-3.1"
    assert first.observation_type == "segmentation"
    assert first.label == "red bicycle"
    assert first.sampling_mode == "native_video"
    assert first.timestamp_ms is None  # fps unknown — never invented
    assert first.request_id == "resp_test"
    assert first.geometry["x1"] == 211 and first.geometry["w"] == 320
    assert first.geometry["confidence"] == 0.91
    # Mask payload (contains a comma) stored verbatim, referenced, undecoded.
    assert first.geometry["mask"] == {"height": 27, "width": 60,
                                      "encoding": "one_bit", "stored": True}
    from pathlib import Path
    assert Path(first.mask_ref).read_text() == "abc,def"
    assert obs[1].geometry["mask"]["encoding"] == "lossless"
    assert "confidence" not in obs[1].geometry


def test_parse_sam_output_zero_matches_and_garbage():
    from vii.providers.visual import parse_sam_output

    assert parse_sam_output("") == []  # documented zero-match outcome
    assert parse_sam_output("not a wire line") == []


# -- provider ----------------------------------------------------------------

def test_sam_provider_remote_url_concept_request(tmp_path):
    from vii.providers.visual import SamVisualPerceptionProvider

    client = _FakeClient()
    provider = SamVisualPerceptionProvider(
        client=client, mask_dir=tmp_path / "masks")
    assert provider.capabilities()["status"] == "configured_unverified"
    assert provider.capabilities()["supports_tracking"] is True
    obs = provider.perceive_video(
        "https://example.com/clip.mp4", asset_id="a1",
        prompts=["red bicycle"])
    assert len(obs) == 3
    payload = client.payloads[0]
    assert payload["model"] == "sam-3.1"
    assert payload["metadata"] == {"mask_encoding": "one_bit",
                                    "include_confidence": "true"}
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "red bicycle"}
    assert content[1] == {"type": "input_video",
                          "video_url": "https://example.com/clip.mp4"}
    assert client.uploads == []  # remote media is never uploaded


def test_sam_provider_local_video_uploads_via_files_api(tmp_path):
    from vii.providers.visual import SamVisualPerceptionProvider

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"synthetic")
    client = _FakeClient()
    provider = SamVisualPerceptionProvider(client=client)
    obs = provider.perceive_video(str(clip), prompts=["van"])
    assert client.uploads == [str(clip)]
    content = client.payloads[0]["input"][0]["content"]
    assert content[1] == {"type": "input_video", "file_id": "file-123"}
    assert obs and all(o.mask_ref is None for o in obs)  # no mask_dir set


def test_sam_provider_typed_errors_and_zero_matches(tmp_path):
    from vii.providers.visual import (
        SamVisualPerceptionProvider,
        VisualPerceptionUnavailableError,
    )

    provider = SamVisualPerceptionProvider(client=_FakeClient())
    with pytest.raises(VisualPerceptionUnavailableError, match="concept"):
        provider.perceive_video("https://example.com/v.mp4")  # no prompts
    with pytest.raises(VisualPerceptionUnavailableError, match="not found"):
        provider.perceive_video(str(tmp_path / "missing.mp4"),
                                prompts=["van"])
    webm = tmp_path / "clip.webm"
    webm.write_bytes(b"synthetic")
    with pytest.raises(VisualPerceptionUnavailableError, match="MP4/MOV"):
        provider.perceive_video(str(webm), prompts=["van"])
    # Zero matches is a valid outcome, not an error.
    empty = SamVisualPerceptionProvider(client=_FakeClient(text=""))
    assert empty.perceive_video(
        "https://example.com/v.mp4", prompts=["unicorn"]) == []
    # No key configured: typed error, nothing sent.
    dead = SamVisualPerceptionProvider(client=None)
    assert dead.capabilities()["status"] == "blocked"
    with pytest.raises(VisualPerceptionUnavailableError, match="no API key"):
        dead.perceive_video("https://example.com/v.mp4", prompts=["van"])


def test_sam_selection_uses_model_api_key_fallback(tmp_path):
    from vii.providers.visual import get_visual_perception_provider

    provider = get_visual_perception_provider(_settings(
        tmp_path, VII_ENABLE_VISUAL_PERCEPTION=True,
        VII_VISUAL_PERCEPTION_PROVIDER="sam",
        MODEL_API_KEY="test-key-not-real"))  # docs: same Bearer key
    assert provider.name == "sam"
    assert provider.model == "sam-3.1"
    assert provider.capabilities()["status"] == "configured_unverified"


# -- pipeline guard ------------------------------------------------------------

def test_pipeline_demo_mode_never_calls_sam(tmp_path):
    from types import SimpleNamespace

    from vii.application.pipeline import Pipeline

    pipe = object.__new__(Pipeline)
    pipe.settings = _settings(
        tmp_path, VII_ENABLE_VISUAL_PERCEPTION=True,
        VII_VISUAL_PERCEPTION_PROVIDER="sam",
        VII_SAM_API_KEY="test-key-not-real")
    logs: list = []
    jobs = SimpleNamespace(log=lambda *a: logs.append(a))
    observations, state = pipe._perceive(
        "job_x", "https://example.com/v.mp4", "sha", True, jobs)
    assert observations == []
    assert state["status"] == "blocked" and state["provider"] == "sam"
    assert logs  # the blocked stage is logged, never silent
