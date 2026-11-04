"""AI-generation detection: parsing, aggregation, pipeline wiring.

All provider calls mocked. No live requests."""
from __future__ import annotations

import json

import pytest


def _client_for(verdicts):
    calls = {"n": 0}

    class _Fake:
        live = True

        def responses_create(self, payload):
            i = calls["n"]
            calls["n"] += 1
            v, c = verdicts[i]
            return {"id": "r", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": json.dumps({"verdict": v, "confidence": c,
                                        "reasons": ["test"]})}]}]}

    return _Fake(), calls


def test_judge_frame_parses_verdict_and_probability():
    from vii.integrity.ai_detection import judge_frame

    client, _ = _client_for([("ai_generated", 0.9)])
    out = judge_frame(b"fake-bytes", client, "m")
    assert out["verdict"] == "ai_generated"
    assert out["ai_probability"] == 0.9
    client2, _ = _client_for([("real", 0.8)])
    out2 = judge_frame(b"fake-bytes", client2, "m")
    assert out2["ai_probability"] == pytest.approx(0.2)


def test_assess_frames_aggregates_and_records_failures(tmp_path):
    from vii.integrity.ai_detection import assess_frames

    good = tmp_path / "f0.jpg"
    good.write_bytes(b"x")

    class _Flaky:
        live = True
        n = 0

        def responses_create(self, payload):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("boom")
            return {"id": "r", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": json.dumps({"verdict": "real",
                                        "confidence": 0.7,
                                        "reasons": []})}]}]}

    out = assess_frames([good, good], _Flaky(), "m", max_frames=2)
    assert out["status"] == "partial"
    assert out["frames_judged"] == 1
    assert out["ai_probability"] == 0.3
    assert any(not f["ok"] for f in out["frames"])


def test_assess_frames_unavailable_without_client(tmp_path):
    from vii.integrity.ai_detection import assess_frames

    out = assess_frames([], None, "m")
    assert out["status"] == "unavailable"
    assert out["ai_probability"] is None


def test_pipeline_defaults_to_disabled(tmp_path):
    from vii.application.services import AnalysisService
    from vii.config import Settings
    from vii.domain.schemas import AnalysisCreate

    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                 VII_STORAGE_DIR=tmp_path, VII_DEMO_MODE=True)
    svc = AnalysisService(s)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/v.mp4"},
        demo=True))
    payload = svc.run(jid)
    assert payload["metadata"]["capabilities"]["ai_detection"] == "disabled"
