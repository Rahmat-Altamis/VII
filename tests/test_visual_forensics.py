"""Visual perception (local provider), manipulation forensics, Bug 1/3 regressions.

Synthetic fixtures only — no provider calls, no credits, no real media.
Forensic assertions check categorical signals and limitations, never a
genuine/fake verdict or probability.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_frames(tmp_path: Path, colors: list[tuple[int, int, int]]) -> list[Path]:
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    frames = []
    for i, color in enumerate(colors):
        p = tmp_path / f"frame_{i:03d}.png"
        Image.new("RGB", (64, 64), color).save(p)
        frames.append(p)
    return frames


def _signal(result, name):
    return next(s for s in result.signals if s.name == name)


# -- Bug 1: SUPPORTED/CONTRADICTED must be constructible with evidence ----

def test_supported_and_contradicted_constructible_with_evidence():
    from pydantic import ValidationError

    from vii.domain.enums import ClaimStatus
    from vii.domain.schemas import ClaimAssessmentIn

    ok = ClaimAssessmentIn(claim_id="c1", status=ClaimStatus.SUPPORTED,
                           explanation="Cited sources corroborate.",
                           evidence_urls=["https://example.com/a"])
    assert ok.status == ClaimStatus.SUPPORTED
    no = ClaimAssessmentIn(claim_id="c2", status=ClaimStatus.CONTRADICTED,
                           explanation="Cited sources refute.",
                           evidence_urls=["https://example.com/b"])
    assert no.status == ClaimStatus.CONTRADICTED
    with pytest.raises(ValidationError):
        ClaimAssessmentIn(claim_id="c3", status=ClaimStatus.SUPPORTED,
                          explanation="ok", evidence_urls=[])
    with pytest.raises(ValidationError):
        ClaimAssessmentIn(claim_id="c4", status=ClaimStatus.CONTRADICTED,
                          explanation="", evidence_urls=["https://example.com/a"])


# -- Forensics -------------------------------------------------------------

def test_forensics_missing_and_remote_media_unavailable(tmp_path):
    from vii.integrity.forensics import assess_manipulation

    assert assess_manipulation(tmp_path / "missing.mp4").status == "unavailable"
    assert assess_manipulation("https://example.com/v.mp4").status == "unavailable"


def test_forensics_missing_frames_and_malformed_metadata(tmp_path):
    from vii.integrity.forensics import assess_manipulation

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic")
    result = assess_manipulation(media, [], metadata={"unexpected": object()})
    assert _signal(result, "frame_reuse").status == "unavailable"
    assert _signal(result, "recompression_error").status == "unavailable"
    # Non-dict-shaped values must not crash provenance evaluation.
    assert _signal(result, "provenance_metadata").status in ("signal", "no_signal")


def test_forensics_frame_reuse_signal_and_no_verdict_fields(tmp_path):
    from vii.integrity.forensics import assess_manipulation
    from vii.media.hashing import phash_frames

    frames = _make_frames(tmp_path, [(200, 30, 30), (30, 30, 200), (200, 30, 30)])
    if len(phash_frames(frames)) < 3:
        pytest.skip("imagehash/Pillow hashing unavailable")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic")
    result = assess_manipulation(
        media, frames, metadata={"format": "mp4", "video_codec": "h264"})
    assert _signal(result, "frame_reuse").status == "signal"
    assert _signal(result, "provenance_metadata").status == "no_signal"
    assert result.status == "signals_detected"
    dumped = result.model_dump()
    assert set(dumped) == {"status", "signals", "detector_used", "limitations"}
    assert "confidence" not in str(dumped).lower()
    assert result.status not in ("fake", "genuine", "real")


def test_forensics_distinct_frames_no_reuse(tmp_path):
    import random

    from vii.integrity.forensics import assess_manipulation
    from vii.media.hashing import phash_frames

    # Structurally distinct fixtures: solid-colour frames are NOT distinct
    # under perceptual hashing (flat images share a DCT signature), and even
    # simple geometric patterns can land within the reuse distance threshold
    # (left-half vs checker measured distance 2, threshold <= 2). Seeded
    # random-noise frames are mutually distant (distance ~32) and
    # deterministic across runs.
    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
    rng = random.Random(20261103)
    frames = []
    for i in range(3):
        img = Image.new("L", (64, 64))
        px = img.load()
        for y in range(64):
            for x in range(64):
                px[x, y] = rng.randrange(256)
        p = tmp_path / f"frame_{i:03d}.png"
        img.convert("RGB").save(p)
        frames.append(p)
    if len(phash_frames(frames)) < 3:
        pytest.skip("imagehash/Pillow hashing unavailable")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic")
    result = assess_manipulation(
        media, frames, metadata={"format": "mp4", "video_codec": "h264"})
    assert _signal(result, "frame_reuse").status == "no_signal"


def test_client_assess_forensics_is_local_and_typed(tmp_path):
    from vii import VII
    from vii.config import Settings
    from vii.domain.schemas import DeepfakeAssessment

    client = VII(settings=Settings(
        VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
        VII_STORAGE_DIR=tmp_path))
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic")
    result = client.assess_forensics(media)
    assert isinstance(result, DeepfakeAssessment)
    assert result.status in ("signals_detected", "no_signals_detected",
                             "unavailable")
    assert client._service is None  # no DB/service built for a local op


# -- Visual perception: local provider ------------------------------------

def test_local_visual_provider_observations(tmp_path, monkeypatch):
    from vii.config import Settings
    from vii.providers.visual import (
        VisualPerceptionUnavailableError,
        get_visual_perception_provider,
    )

    provider = get_visual_perception_provider(Settings(
        _env_file=None, VII_ENABLE_VISUAL_PERCEPTION=True,
        VII_VISUAL_PERCEPTION_PROVIDER="local", VII_API_HOST="127.0.0.1"))
    assert provider.name == "local"
    caps = provider.capabilities()
    assert caps["supports_tracking"] is False  # never claimed
    if caps["status"] != "available_local":
        pytest.skip(f"local provider unavailable: {caps['notes']}")

    frames = _make_frames(
        tmp_path, [(20, 20, 20), (25, 25, 25), (230, 230, 230)])
    monkeypatch.setattr(
        "vii.media.ffmpeg.sample_frames",
        lambda src, out_dir, fps, max_frames, ffmpeg_bin: frames)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"synthetic")

    observations = provider.perceive_video(str(clip), asset_id="asset-1")
    assert observations
    assert observations[0].observation_type == "shot_segment"
    assert all(o.provider == "local" for o in observations)
    assert all(o.mask_ref is None for o in observations)  # no fake masks
    with pytest.raises(VisualPerceptionUnavailableError):
        provider.perceive_video(str(clip), prompts=["person"])
    with pytest.raises(VisualPerceptionUnavailableError):
        provider.perceive_video("https://example.com/v.mp4")


# -- Pipeline / repository regressions ------------------------------------

def test_pipeline_report_contains_forensics_with_five_dimensions(settings):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate

    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    payload = svc.run(jid)
    assert set(payload["dimensions"]) == {
        "claim_verification", "supporting_contradicting_evidence",
        "media_origin", "originality", "uncertainty_limitations"}
    forensic = payload["dimensions"]["media_origin"]["manipulation_forensics"]
    assert forensic["status"] in ("signals_detected", "no_signals_detected",
                                   "unavailable")
    assert forensic["detector_used"]  # honest detector description present
    # Alignment: media_origin itself must not contradict the embedded
    # forensics by still claiming no detector was run.
    origin = payload["dimensions"]["media_origin"]
    assert origin["detector_used"] == forensic["detector_used"]
    assert "no AI-detector claimed" not in origin["detector_used"]


def test_clear_job_artifacts_and_rerun_do_not_duplicate(settings):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate
    from vii.persistence.repositories import AnalysisRepo, JobRepo

    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    with svc.Session() as db:
        repo = AnalysisRepo(db)
        # Simulate a partial earlier run plus preserved audit log.
        repo.add_claim(jid, f"{jid}_c001", "stale claim", "factual", None, None)
        repo.add_evidence(jid, f"{jid}_c001", "https://example.com/x",
                          "t", "s", "p", "meta_web_search", "r1")
        JobRepo(db).log(jid, "ingestion", "audit line must survive")
    payload = svc.run(jid)
    detail = svc.get(jid)
    ids = [c["id"] for c in detail["claims"]]
    assert len(ids) == len(set(ids))  # no duplicate claim rows after rerun
    assert len(ids) == len(payload["claims"])
    assert detail["status"] == "succeeded"
    with svc.Session() as db:
        assert any("audit line" in log.message
                   for log in JobRepo(db).logs(jid))  # logs preserved
