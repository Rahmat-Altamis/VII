"""Phase 5 (handoff): API hardening + cleanup. No live calls."""
from __future__ import annotations


def test_check_api_key_uses_constant_time_compare(monkeypatch):
    import vii.config as cfg
    seen = []
    cfg.hmac.compare_digest if hasattr(cfg, "hmac") else None
    import hmac as hmac_mod
    orig = hmac_mod.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return orig(a, b)

    monkeypatch.setattr(hmac_mod, "compare_digest", spy)
    s = cfg.Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                     VII_REQUIRE_AUTH=True, VII_API_KEYS="good-key",
                     VII_STORAGE_DIR="/tmp/vii-p5")
    assert s.check_api_key("good-key")[0] is True
    assert seen, "check_api_key must compare with hmac.compare_digest"


def test_consumer_id_header_is_sanitized_for_filesystem():
    import vii.api.v1 as v1
    cid = v1.consumer_id(authorization=None, x_consumer="../../evil")
    assert "/" not in cid and ".." not in cid


def test_webhook_secret_comes_from_settings(tmp_path, monkeypatch):
    import vii.api.v1 as v1
    from vii.config import Settings
    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_WEBHOOK_ENABLED=True, VII_WEBHOOK_SECRET="test-secret",
                 VII_STORAGE_DIR=tmp_path)
    assert s.webhook_secret == "test-secret"
    monkeypatch.setattr(v1, "get_settings", lambda: s)
    monkeypatch.setattr(v1, "_webhook_target_ok", lambda url: (True, "ok"))
    v1._stash_webhook("job_s", "https://hooks.example.com/vii", "default")
    posts = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://hooks.example.com/vii"

        def read(self):
            return b""

    class _Opener:
        def open(self, req, timeout=None):
            posts.append(req)
            return _Resp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: _Opener())
    v1._fire_webhook("job_s", "succeeded", "default")
    assert len(posts) == 1
    import hashlib
    import hmac as hmac_mod
    body = posts[0].data
    expected = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert posts[0].get_header("X-vii-signature") == f"sha256={expected}"


def test_report_path_traversal_rejected(settings, monkeypatch):
    from fastapi.testclient import TestClient

    import vii.api.v1 as v1
    from vii.api.app import app
    from vii.application.services import AnalysisService
    monkeypatch.setattr(v1, "_service", AnalysisService(settings))
    monkeypatch.setattr(v1, "get_settings", lambda: settings)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/v1/analyses/..%2F..%2Fsecret/report")
    assert r.status_code in (400, 404)


def test_corpus_record_written_after_analysis(settings, tmp_path):
    import json as _json
    import struct
    from pathlib import Path

    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate

    def _box(t, p):
        return struct.pack(">I", len(p) + 8) + t + p

    media = tmp_path / "clip.mp4"
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5000))
    media.write_bytes(ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16))
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "local_file", "local_path": str(media)}, demo=True))
    svc.run(jid)
    corpus = Path(settings.storage_dir) / "corpus"
    records = list(corpus.glob("*.json"))
    assert records, "a corpus record must be written for local media"
    data = _json.loads(records[0].read_text())
    assert len(data.get("sha256", "")) == 64
