"""Ingestion-only media inspection: validation, hashing, signatures.

These tests use synthetic byte fixtures only. The ingestion-only path must
never create an analysis job, enqueue a worker, or call a provider — that
is asserted explicitly, not assumed.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from vii.media.ingestion import inspect_local_media, sniff_container


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _make_mp4(path: Path, duration_s: float = 5.0, timescale: int = 1000) -> Path:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale,
                                                           int(duration_s * timescale)))
    mp4 = ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16)
    path.write_bytes(mp4)
    return path


def test_inspect_valid_mp4_without_ffmpeg(tmp_path):
    p = _make_mp4(tmp_path / "clip.mp4", duration_s=5.0)
    result = inspect_local_media(p, max_mb=512, max_seconds=3600, ffprobe_bin=None)
    assert result.signature_ok is True
    assert result.container == "mp4"
    assert result.extension == ".mp4"
    assert result.native_video_ready is True
    assert result.needs_conversion is False
    assert result.duration_s == pytest.approx(5.0)
    assert result.duration_source == "mp4_mvhd"  # parsed locally, no ffprobe
    assert result.sha256 == hashlib.sha256(p.read_bytes()).hexdigest()
    assert result.size_bytes == p.stat().st_size


def test_inspect_rejects_missing_and_empty(tmp_path):
    with pytest.raises(ValueError, match="file not found"):
        inspect_local_media(tmp_path / "nope.mp4")
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="file is empty"):
        inspect_local_media(empty)


def test_inspect_rejects_too_large_and_unsupported(tmp_path):
    p = _make_mp4(tmp_path / "clip.mp4")
    with pytest.raises(ValueError, match="file too large"):
        inspect_local_media(p, max_mb=0)  # any real file exceeds a 0MB cap
    weird = tmp_path / "clip.xyz"
    weird.write_bytes(b"whatever")
    with pytest.raises(ValueError, match="unsupported format"):
        inspect_local_media(weird)


def test_inspect_rejects_signature_mismatch(tmp_path):
    fake = tmp_path / "renamed.mp4"
    fake.write_bytes(b"this is plain text, not an MP4 container at all")
    with pytest.raises(ValueError, match="signature mismatch"):
        inspect_local_media(fake)
    assert sniff_container(fake) == "unknown"


def test_inspect_enforces_duration_limit(tmp_path):
    p = _make_mp4(tmp_path / "long.mp4", duration_s=7200.0)
    with pytest.raises(ValueError, match="video too long"):
        inspect_local_media(p, max_seconds=3600, ffprobe_bin=None)


def test_inspect_unknown_duration_is_reported_not_guessed(tmp_path):
    p = tmp_path / "no_mvhd.mp4"
    p.write_bytes(_box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isom")
                  + _box(b"mdat", b"\x00" * 8))
    result = inspect_local_media(p, ffprobe_bin=None)
    assert result.duration_s is None
    assert result.duration_source == "unknown"
    assert any("not guessed" in note for note in result.limitations)
    assert result.native_video_ready is True  # signature still verified


def test_sniff_container_families(tmp_path):
    assert sniff_container(_make_mp4(tmp_path / "a.mp4")) == "mp4"
    webm = tmp_path / "a.webm"
    webm.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 28 + b"webm")
    assert sniff_container(webm) in ("webm", "mkv")  # EBML family
    avi = tmp_path / "a.avi"
    avi.write_bytes(b"RIFF" + b"\x00" * 4 + b"AVI " + b"\x00" * 8)
    assert sniff_container(avi) == "avi"


def test_ingestion_only_makes_no_provider_calls_and_creates_no_jobs(tmp_path, monkeypatch):
    """Behavioral proof: provider, pipeline, and worker entry points are
    rigged to record any use; ingestion-only inspection must touch none."""
    calls: list[str] = []

    from vii.application.pipeline import Pipeline
    from vii.application.worker import Worker
    from vii.meta.client import MetaClient

    monkeypatch.setattr(MetaClient, "responses_create",
                        lambda *a, **k: calls.append("responses_create"))
    monkeypatch.setattr(MetaClient, "upload_video",
                        lambda *a, **k: calls.append("upload_video"))
    monkeypatch.setattr(MetaClient, "transcribe",
                        lambda *a, **k: calls.append("transcribe"))
    monkeypatch.setattr(Pipeline, "create_job",
                        lambda *a, **k: calls.append("create_job"))
    monkeypatch.setattr(Worker, "enqueue",
                        lambda *a, **k: calls.append("enqueue"))

    p = _make_mp4(tmp_path / "clip.mp4")
    result = inspect_local_media(p, ffprobe_bin=None)
    assert result.sha256
    assert calls == []  # zero provider calls, zero jobs, zero enqueues


def test_ingestion_module_has_no_provider_or_job_imports():
    """Import-boundary proof complementing the behavioral test above."""
    src = Path(inspect_local_media.__module__.replace(".", "/")).with_suffix(".py")
    source = (Path(__file__).resolve().parent.parent / "src" / src).read_text()
    import_lines = [ln for ln in source.splitlines()
                    if ln.startswith(("import ", "from "))]
    assert not any("vii.meta" in ln or "vii.providers" in ln for ln in import_lines)
    assert not any("pipeline" in ln or "worker" in ln or "persistence" in ln
                   for ln in import_lines)


def test_cli_ingest_only_roundtrip(tmp_path, capsys):
    from vii.main import ingest_only

    p = _make_mp4(tmp_path / "clip.mp4")
    assert ingest_only(str(p)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert payload["container"] == "mp4"

    assert ingest_only(str(tmp_path / "missing.mp4")) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["ok"] is False
    assert rejected["error"] == "InvalidUploadError"
