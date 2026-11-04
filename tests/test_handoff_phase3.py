"""Phase 3 (handoff): pipeline signature validation, upload content checks,
SSRF is_global + fail-closed DNS + redirect revalidation. No network."""
from __future__ import annotations

import socket
import struct
from pathlib import Path

import pytest

from vii.domain.schemas import VideoSourceIn
from vii.media import ingestion


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _make_mp4(path: Path) -> Path:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5000))
    path.write_bytes(ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16))
    return path


# -- pipeline local-path signature validation --------------------------------

def test_pipeline_rejects_renamed_text_file(settings, tmp_path):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"plain text, not a video container")
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "local_file", "local_path": str(fake)}, demo=True))
    with pytest.raises(ValueError):
        svc.run(jid)
    assert svc.get(jid)["status"] == "failed"


# -- SSRF ----------------------------------------------------------------------

def _fake_dns(ip: str):
    def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return _getaddrinfo


def test_ssrf_blocks_cgnat_via_is_global(monkeypatch):
    monkeypatch.setattr(ingestion.socket, "getaddrinfo", _fake_dns("100.64.0.1"))
    with pytest.raises(ValueError, match="SSRF"):
        ingestion.validate_source(
            VideoSourceIn(kind="public_url", url="https://example.com/v.mp4"),
            512, Path("/tmp"))


def test_ssrf_dns_failure_is_fail_closed(monkeypatch):
    def _boom(host, port, family=0, type=0, proto=0, flags=0):
        raise socket.gaierror("name resolution failed")
    monkeypatch.setattr(ingestion.socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError, match="SSRF"):
        ingestion.validate_source(
            VideoSourceIn(kind="public_url", url="https://example.com/v.mp4"),
            512, Path("/tmp"))


def test_ssrf_allows_public_ip(monkeypatch):
    monkeypatch.setattr(ingestion.socket, "getaddrinfo", _fake_dns("8.8.8.8"))
    out = ingestion.validate_source(
        VideoSourceIn(kind="public_url", url="https://example.com/v.mp4"),
        512, Path("/tmp"))
    assert out["host"] == "example.com"


# -- upload content checks -----------------------------------------------------

def test_upload_rejects_fake_mp4_content(settings, monkeypatch):
    from fastapi.testclient import TestClient

    import vii.api.v1 as v1
    from vii.api.app import app
    from vii.application.services import AnalysisService
    monkeypatch.setattr(v1, "_service", AnalysisService(settings))
    monkeypatch.setattr(v1, "get_settings", lambda: settings)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/uploads", files={"file": ("fake.mp4", b"plain text not video")})
    assert r.status_code == 400


def test_upload_accepts_real_mp4_signature(settings, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import vii.api.v1 as v1
    from vii.api.app import app
    from vii.application.services import AnalysisService
    monkeypatch.setattr(v1, "_service", AnalysisService(settings))
    monkeypatch.setattr(v1, "get_settings", lambda: settings)
    c = TestClient(app, raise_server_exceptions=False)
    good = _make_mp4(tmp_path / "good.mp4")
    r = c.post("/v1/uploads",
               files={"file": ("good.mp4", good.read_bytes())})
    assert r.status_code == 201
    assert r.json()["sha256"]


def test_webhook_target_blocks_cgnat_and_unresolvable(monkeypatch):
    import vii.api.v1 as v1
    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns("100.64.0.1"))
    ok, _ = v1._webhook_target_ok("https://hooks.example.com/x")
    assert ok is False

    def _boom(host, port, family=0, type=0, proto=0, flags=0):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    ok, _ = v1._webhook_target_ok("https://hooks.example.com/x")
    assert ok is False
