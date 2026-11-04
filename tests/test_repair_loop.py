"""Repair-loop regressions: migration, evidence, transcription, SAM,
partial-result orchestration, redaction. All provider behavior mocked."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from vii.config import Settings


def _s(tmp_path, **kw):
    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("VII_STORAGE_DIR", tmp_path)
    kw.setdefault("VII_DATABASE_URL", f"sqlite:///{tmp_path}/vii.db")
    return Settings(_env_file=None, **kw)


def _old_schema_db(path):
    """Pre-Phase-1 database: evidence_sources without the new columns."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE evidence_sources (id INTEGER PRIMARY KEY, "
               "job_id VARCHAR(64), claim_id VARCHAR(64), url TEXT, "
               "title TEXT, snippet TEXT, publisher VARCHAR(256), "
               "method VARCHAR(64), search_response_id VARCHAR(128), "
               "retrieved_at TIMESTAMP)")
    db.execute("INSERT INTO evidence_sources (job_id, claim_id, url, title) "
               "VALUES ('j1', 'c1', 'https://x.example/a', 'Old row')")
    db.commit()
    db.close()


def test_migration_upgrades_old_schema_and_preserves_rows(tmp_path):
    from sqlalchemy import inspect

    from vii.persistence.db import init_db

    db_path = tmp_path / "old.db"
    _old_schema_db(db_path)
    factory = init_db(f"sqlite:///{db_path}", tmp_path / "store")
    with factory() as s:
        from vii.persistence.models import EvidenceSource

        row = s.query(EvidenceSource).filter_by(job_id="j1").one()
        assert row.title == "Old row"
        assert row.relationship == ""  # new column present, backfilled default
        assert row.publication_date == ""
        versions = [r[0] for r in s.execute(
            __import__("sqlalchemy").text(
                "SELECT version FROM vii_schema_migrations"))]
        assert "0002_evidence_relationship_publication_date" in versions
    assert "relationship" in {c["name"] for c in
                               inspect(factory().get_bind()).get_columns(
                                   "evidence_sources")}


def test_migration_idempotent_and_fresh_init_clean(tmp_path):
    from vii.persistence.db import init_db
    from vii.persistence.migrations import migrate

    factory = init_db(f"sqlite:///{tmp_path}/fresh.db", tmp_path / "store")
    engine = factory().get_bind()
    assert migrate(engine) == []  # second application is a no-op
    insp_cols = {c["name"] for c in
                 __import__("sqlalchemy").inspect(engine).get_columns(
                     "evidence_sources")}
    assert {"relationship", "publication_date"} <= insp_cols


def test_evidence_insert_readback_missing_meta_and_dedupe(tmp_path):
    from vii.persistence.db import init_db
    from vii.persistence.repositories import AnalysisRepo

    factory = init_db(f"sqlite:///{tmp_path}/e.db", tmp_path / "store")
    with factory() as s:
        repo = AnalysisRepo(s)
        assert repo.add_evidence("j", "c", "https://x.example/a", "T", "S",
                                 "", "meta_web_search", "r1", None, None) is True
        assert repo.add_evidence("j", "c", "https://x.example/a", "T", "S",
                                 "", "meta_web_search", "r1") is False
        rows = repo.evidence_for_job("j")
        assert len(rows) == 1 and rows[0].title == "T"


class _HttpError(Exception):
    def __init__(self, status, body=""):
        super().__init__(f"Error code: {status} - {body}")
        self.response = SimpleNamespace(status_code=status)


def test_transcribe_404_is_provider_error_single_attempt(tmp_path, monkeypatch):
    import vii.meta.client as cm
    monkeypatch.setattr(cm.time, "sleep", lambda _s: None)
    from vii.errors import ProviderError
    from vii.meta.client import MetaClient

    c = MetaClient("k", "https://api.example/v1", "m", max_retries=2)
    calls = {"n": 0}

    def _post(*a, **k):
        calls["n"] += 1
        return SimpleNamespace(status_code=404, text="no such route",
                               json=lambda: {})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    with pytest.raises(ProviderError, match="404"):
        c.transcribe(str(audio), _post=_post)
    assert calls["n"] == 1  # never retried


def test_transcribe_success_returns_asr_body(tmp_path):
    from vii.meta.client import MetaClient

    c = MetaClient("k", "https://api.example/v1", "m")

    def _post(*a, **k):
        return SimpleNamespace(status_code=200, text="{}",
                               json=lambda: {"sessionId": "s1",
                                             "transcript": "hi",
                                             "audioDurationMs": 1500,
                                             "turns": []})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    out = c.transcribe(str(audio), _post=_post)
    assert out["sessionId"] == "s1" and out["text"] == "hi"


def test_transcription_404_maps_to_unsupported_engine(tmp_path, monkeypatch):
    from vii.errors import UnsupportedCapabilityError
    from vii.meta.transcription import transcribe_audio

    class _Boom:
        live = True

        def transcribe(self, *a, **k):
            raise UnsupportedCapabilityError("endpoint gone")

    monkeypatch.setattr("vii.media.ffmpeg.probe",
                        lambda *a, **k: {"format": {"duration": "5"},
                                         "streams": [{"codec_type": "audio"}]})
    def _wav(src, dst, *a, **k):
        from pathlib import Path as _P
        _P(dst).write_bytes(b"x")
        return _P(dst)

    monkeypatch.setattr("vii.media.ffmpeg.extract_audio_wav", _wav)
    tr = transcribe_audio(tmp_path / "clip.mp4", _s(tmp_path), _Boom())
    assert tr.engine == "transcription-unsupported"
    assert tr.segments == []  # never fabricated


def test_sam_failure_is_degraded_blocked_not_fatal(tmp_path):
    from vii.providers.visual import (
        SamVisualPerceptionProvider,
        VisualPerceptionUnavailableError,
    )

    class _Fail:
        live = True

        def responses_create(self, payload):
            raise _HttpError(503, "service overloaded")

        def upload_video(self, path):
            return {"file_id": "f"}

    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    with pytest.raises(VisualPerceptionUnavailableError, match="failed"):
        SamVisualPerceptionProvider(client=_Fail()).perceive_video(
            str(media), prompts=["car"])


def test_sam_success_parses_documented_grammar(tmp_path):
    from vii.providers.visual import SamVisualPerceptionProvider

    class _Ok:
        live = True

        def responses_create(self, payload):
            return {"id": "r1", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": "<0f>1<|box;x1=1;y1=2;x2=3;y2=4;w=8;h=8|>"
                            "<|mask;x=0;y=0;data=8,8,~PAYLOAD|>"}]}]}

        def upload_video(self, path):
            return {"file_id": "f"}

    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    obs = SamVisualPerceptionProvider(client=_Ok()).perceive_video(
        str(media), prompts=["car"])
    assert len(obs) == 1 and obs[0].object_id == "1"


def test_search_failure_keeps_understanding_and_marks_partial(tmp_path):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate

    class _Fake:
        live = True
        calls = 0

        def upload_video(self, path, purpose="user_data"):
            return {"file_id": "f"}

        def responses_create(self, payload):
            if "tools" in payload:
                self.calls += 1
                if self.calls == 2:
                    raise _HttpError(500, "search exploded")
                return {"id": "s", "output": [
                    {"type": "web_search_call", "id": "ws",
                     "results": [{"url": "https://www.nasa.gov/a",
                                  "title": "N", "snippet": "s",
                                  "relationship": "supports"}]},
                    {"type": "message", "content": [{
                        "type": "output_text", "text": "x",
                        "annotations": [{"type": "url_citation",
                                         "url": "https://www.nasa.gov/a"}]}]}]}
            return {"id": "u", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": json.dumps(
                        {"summary": "v", "factual_claims": [
                            {"text": "Claim one is true."},
                            {"text": "Claim two is true."}]})}]}]}

    svc = AnalysisService(_s(tmp_path, MODEL_API_KEY="test-key-not-real"))
    svc.pipeline.client = _Fake()
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/v.mp4"}))
    payload = svc.run(jid)
    assert svc.get(jid)["status"] == "succeeded"  # partial success, not failed
    assert len(payload["claims"]) == 2  # understanding results kept
    assert payload["metadata"]["capabilities"]["evidence_search"] == "partial"
    assert any("insufficient" in str(c["status"]) for c in payload["claims"])
    assert payload["sources"], "successful search persisted"


def test_new_error_paths_redact_secrets():
    from vii.meta.client import _classify_error
    err = _classify_error(_HttpError(400, "key sk-live-abcdef1234567890 bad"))
    assert "sk-live" not in str(err)
