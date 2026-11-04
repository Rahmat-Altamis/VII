"""Public library API: ``from vii import VII`` and the export surface.

These tests exercise the supported downstream contract only. They use
synthetic byte fixtures and mocked application services, no real API
keys, no network, no provider credits, no real video content.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import vii
from vii import VII


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _make_mp4(path: Path, duration_s: float = 5.0, timescale: int = 1000) -> Path:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(
        ">IIII", 0, 0, timescale, int(duration_s * timescale)))
    path.write_bytes(ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16))
    return path


def _client(tmp_path, **overrides) -> VII:
    from vii.config import Settings

    kw = {
        "VII_DATABASE_URL": f"sqlite:///{tmp_path}/vii.db",
        "VII_STORAGE_DIR": tmp_path,
    }
    kw.update(overrides)
    return VII(settings=Settings(_env_file=None, **kw))


def test_public_export_surface_is_deliberate():
    for name in ("VII", "Settings", "get_settings", "AnalysisCreate",
                 "VideoSourceIn", "MediaIngestionResult", "OriginalityResult",
                 "ReportPayload", "VIIError", "ProviderConfigurationError",
                 "ProviderError", "InvalidUploadError"):
        assert name in vii.__all__
        assert hasattr(vii, name)
    # Internal implementation modules are not promoted to public API.
    for name in ("AnalysisService", "Pipeline", "MetaClient", "create_app"):
        assert name not in vii.__all__


def test_import_vii_pulls_no_heavy_runtime_modules():
    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; sys.path.insert(0, 'src'); import vii; "
        "heavy = [m for m in ('fastapi', 'uvicorn', 'sqlalchemy', 'alembic', "
        "'openai', 'PIL', 'imagehash', 'PySide6') if m in sys.modules]; "
        "assert not heavy, heavy; print(vii.__version__)"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=root,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == vii.__version__


def test_construction_has_no_side_effects(tmp_path):
    storage = tmp_path / "storage"
    client = _client(tmp_path, VII_STORAGE_DIR=storage)
    assert client._service is None  # no DB/service built at construction
    assert not storage.exists()  # no directories created at construction
    assert "test" not in repr(client)  # repr carries no key material


def test_explicit_api_key_and_repr_redaction(tmp_path):
    client = VII(api_key="test-key-not-real", storage_dir=tmp_path)
    assert client.settings.has_api_key is True
    assert client.settings.live_mode is True
    assert "test-key-not-real" not in repr(client)


def test_settings_and_overrides_are_mutually_exclusive(tmp_path):
    from vii.config import Settings

    with pytest.raises(ValueError, match="not both"):
        VII("some-key", settings=Settings(_env_file=None, VII_STORAGE_DIR=tmp_path))


def test_inspect_media_and_sha256_via_client(tmp_path):
    client = _client(tmp_path)
    media = _make_mp4(tmp_path / "clip.mp4", duration_s=5.0)

    result = client.inspect_media(media)
    assert result.container == "mp4"
    assert result.signature_ok is True
    assert result.duration_s == pytest.approx(5.0)
    assert result.sha256 == hashlib.sha256(media.read_bytes()).hexdigest()
    assert client.sha256(media) == result.sha256


def test_inspect_media_rejects_missing_file(tmp_path):
    from vii.errors import InvalidUploadError

    client = _client(tmp_path)
    with pytest.raises(InvalidUploadError):
        client.inspect_media(tmp_path / "missing.mp4")


def test_assess_originality_via_client_exact_duplicate(tmp_path):
    """Client-level regression for the originality digest initialization:
    a local file must return its real SHA-256 (never crash / empty)."""
    client = _client(tmp_path)
    media = tmp_path / "clip.mp4"
    payload = b"synthetic-public-api-fixture"
    media.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "known1.json").write_text(
        json.dumps({"sha256": digest, "phashes": []}))

    result = client.assess_originality(media, corpus)
    assert result.sha256 == digest
    assert result.exact_duplicate_of == "known1"


def test_validate_dataset_missing_valid_and_invalid(tmp_path):
    client = _client(tmp_path)

    missing = client.validate_dataset(tmp_path / "absent.csv")
    assert missing.exists is False  # normal state, not an exception

    good = tmp_path / "good.csv"
    good.write_text(
        "video_id,source_url,platform,storage_ref,sha256,duration_s,title\n"
        "v001,https://example.com/a.mp4,generic,,,12.5,Synthetic clip\n")
    report = client.validate_dataset(good)
    assert report.ok is True
    assert report.valid_rows == 1

    bad = tmp_path / "bad.csv"
    bad.write_text("source_url\nhttps://example.com/a.mp4\n")
    bad_report = client.validate_dataset(bad)
    assert bad_report.ok is False
    assert bad_report.errors  # missing required video_id column


def test_analyze_without_key_fails_before_any_service(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = _client(tmp_path)
    from vii.errors import ProviderConfigurationError

    with pytest.raises(ProviderConfigurationError, match="MODEL_API_KEY"):
        client.analyze("https://example.com/clip.mp4")
    assert client._service is None  # failed before DB/service construction


def test_analyze_delegates_with_mapped_sources(tmp_path, monkeypatch):
    captured: dict = {}

    class FakeService:
        def __init__(self, settings):
            captured["settings"] = settings

        def create(self, req, consumer="default"):
            captured["req"] = req
            return "job-1"

        def run(self, job_id, progress=None):
            captured["job_id"] = job_id
            return {"job_id": job_id, "offline": False}

    monkeypatch.setattr(
        "vii.application.services.AnalysisService", FakeService)
    client = _client(tmp_path, MODEL_API_KEY="test-key-not-real")

    payload = client.analyze("https://example.com/clip.mp4", title="T")
    assert payload == {"job_id": "job-1", "offline": False}
    req = captured["req"]
    assert req.source.kind.value == "public_url"
    assert req.source.url == "https://example.com/clip.mp4"
    assert req.title == "T"

    client.analyze(tmp_path / "local.mp4")
    assert captured["req"].source.kind.value == "local_file"


def test_analyze_rejects_title_with_prebuilt_request(tmp_path):
    from vii.domain.schemas import AnalysisCreate

    client = _client(tmp_path, MODEL_API_KEY="test-key-not-real")
    req = AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/v.mp4"})
    with pytest.raises(ValueError, match="AnalysisCreate"):
        client.analyze(req, title="conflict")


def test_close_is_idempotent_and_context_manager_works(tmp_path):
    client = _client(tmp_path)
    client.close()
    client.close()  # no service was built: still a no-op
    with _client(tmp_path) as ctx:
        assert isinstance(ctx, VII)
    ctx.close()
