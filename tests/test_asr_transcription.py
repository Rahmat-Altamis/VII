"""Muse Voice Transcribe integration (documented /asr/transcribe contract).

All provider responses are mocked; no live calls, no credentials."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vii.config import Settings
from vii.meta.client import MetaClient


def _s(tmp_path, **kw):
    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("VII_STORAGE_DIR", tmp_path)
    kw.setdefault("VII_DATABASE_URL", f"sqlite:///{tmp_path}/vii.db")
    return Settings(_env_file=None, **kw)


def _resp(code, body):
    return SimpleNamespace(status_code=code, text=json.dumps(body),
                           json=lambda: body)


def test_transcribe_url_never_doubles_v1():
    assert (MetaClient("k", "https://api.meta.ai/v1", "m").transcribe_url()
            == "https://api.meta.ai/v1/asr/transcribe")
    assert (MetaClient("k", "https://api.meta.ai/v1/", "m").transcribe_url()
            == "https://api.meta.ai/v1/asr/transcribe")


def test_multipart_request_and_auth_header(tmp_path):
    seen = {}

    def _post(url, params=None, headers=None, files=None, timeout=None):
        seen.update(url=url, headers=headers, files=files, params=params)
        return _resp(200, {"sessionId": "s", "transcript": "t",
                           "audioDurationMs": 100, "turns": []})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....")
    MetaClient("test-key-not-real", "https://api.meta.ai/v1", "m").transcribe(
        str(audio), _post=_post)
    assert seen["url"].endswith("/asr/transcribe")
    assert "sessionId" in seen["params"]
    assert seen["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert seen["headers"]["Accept"] == "application/json"
    req_name, req_json, req_type = seen["files"]["request"]
    cfg = json.loads(req_json)
    assert (req_name, req_type) == (None, "application/json")
    assert cfg["model"] == "muse-voice-transcribe-1.0"
    assert cfg["audioEncoding"] == "WAV" and cfg["mode"] == "DIARIZATION"
    assert seen["files"]["audio"][2] == "audio/wav"


def test_key_never_in_logs_or_errors(tmp_path, caplog):
    import logging

    def _post(*a, **k):
        return _resp(400, {"message": "bad request"})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    with pytest.raises(Exception, match="400"):
        MetaClient("test-key-not-real", "https://api.meta.ai/v1", "m",
                   max_retries=0).transcribe(str(audio), _post=_post)
    with caplog.at_level(logging.WARNING, logger="vii.meta"):
        try:
            MetaClient("test-key-not-real", "https://api.meta.ai/v1", "m",
                       max_retries=0).transcribe(str(audio), _post=_post)
        except Exception:
            pass
    assert "test-key-not-real" not in caplog.text


def test_wav_extraction_normalizes_format(tmp_path):
    pytest.importorskip("shutil")
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    from vii.media.ffmpeg import extract_audio_wav

    src = tmp_path / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2",
                    "-f", "lavfi", "-i", "color=black:size=16x16:duration=2",
                    "-shortest", str(src)], check=True, timeout=60)
    out = extract_audio_wav(src, tmp_path / "out.wav", "ffmpeg",
                            start_s=0.0, end_s=1.0)
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                           "-show_entries", "stream=codec_name,channels,"
                           "sample_rate,sample_fmt",
                           "-of", "default=noprint_wrappers=1", str(out)],
                          capture_output=True, text=True, timeout=60)
    assert "codec_name=pcm_s16le" in info.stdout
    assert "channels=1" in info.stdout
    assert "sample_rate=24000" in info.stdout
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(out)],
                         capture_output=True, text=True, timeout=60)
    assert float(dur.stdout.strip()) == pytest.approx(1.0, abs=0.1)


def test_turn_parsing_timestamps_and_speakers():
    from vii.meta.transcription import parse_asr_response

    segs = parse_asr_response({
        "transcript": "How is the weather? It is raining.",
        "audioDurationMs": 8240,
        "turns": [
            {"turnId": 1, "startMs": 1520, "endMs": 4640,
             "transcript": "How is the weather?", "speaker": "A"},
            {"turnId": 2, "startMs": 5900, "endMs": 8240,
             "transcript": "It is raining.", "speaker": "B"},
        ]})
    assert [(s.start_s, s.end_s, s.speaker) for s in segs] == [
        (1.52, 4.64, "A"), (5.9, 8.24, "B")]
    shifted = parse_asr_response(
        {"turns": [{"startMs": 0, "endMs": 1000, "transcript": "x"}]},
        offset_s=540.0)
    assert (shifted[0].start_s, shifted[0].end_s) == (540.0, 541.0)


def test_no_audio_stream_is_explicit(tmp_path, monkeypatch):
    from vii.meta.transcription import transcribe_audio

    monkeypatch.setattr("vii.media.ffmpeg.probe",
                        lambda *a, **k: {"format": {"duration": "5"},
                                         "streams": [{"codec_type": "video"}]})
    tr = transcribe_audio(tmp_path / "v.mp4", _s(tmp_path),
                          SimpleNamespace(live=True))
    assert tr.engine == "no-audio-stream" and tr.segments == []


def test_conversion_failure_is_explicit(tmp_path, monkeypatch):
    from vii.media.ffmpeg import FFmpegError
    from vii.meta.transcription import transcribe_audio

    monkeypatch.setattr("vii.media.ffmpeg.probe",
                        lambda *a, **k: {"format": {"duration": "5"},
                                         "streams": [{"codec_type": "audio"}]})

    def _boom(*a, **k):
        raise FFmpegError("unsupported input codec")

    monkeypatch.setattr("vii.media.ffmpeg.extract_audio_wav", _boom)
    tr = transcribe_audio(tmp_path / "v.mp4", _s(tmp_path),
                          SimpleNamespace(live=True))
    assert tr.engine == "ffmpeg-error" and tr.segments == []


@pytest.mark.parametrize("code,retryable", [(400, 0), (404, 0), (413, 0),
                                            (429, 1), (500, 1)])
def test_status_handling(code, retryable, tmp_path, monkeypatch):
    import vii.meta.client as cm
    monkeypatch.setattr(cm.time, "sleep", lambda _s: None)
    from vii.errors import ProviderError, ProviderRateLimitError

    calls = {"n": 0}

    def _post(*a, **k):
        calls["n"] += 1
        return _resp(code, {"message": "x"})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    with pytest.raises(ProviderError):
        MetaClient("k", "https://api.example/v1", "m",
                   max_retries=1).transcribe(str(audio), _post=_post)
    assert calls["n"] == 1 + retryable
    if code == 429:
        try:
            MetaClient("k", "https://api.example/v1", "m",
                       max_retries=0).transcribe(str(audio), _post=_post)
        except ProviderRateLimitError:
            pass
        else:
            pytest.fail("429 must map to ProviderRateLimitError")


def test_body_and_duration_limits_enforced(tmp_path, monkeypatch):
    import vii.meta.transcription as tm
    from vii.meta.transcription import transcribe_audio

    monkeypatch.setattr("vii.media.ffmpeg.probe",
                        lambda *a, **k: {"format": {"duration": "5"},
                                         "streams": [{"codec_type": "audio"}]})
    def _wav(src, dst, *a, **k):
        Path(dst).write_bytes(b"x" * 64)
        return Path(dst)

    monkeypatch.setattr("vii.media.ffmpeg.extract_audio_wav", _wav)
    monkeypatch.setattr(tm, "MAX_BODY_BYTES", 16)
    tr = transcribe_audio(tmp_path / "v.mp4", _s(tmp_path),
                          SimpleNamespace(live=True))
    assert tr.engine == "transcription-audio-too-large"


def test_transcript_persisted_and_wav_cleaned_up(tmp_path, monkeypatch):
    from vii.meta.transcription import transcribe_audio

    monkeypatch.setattr("vii.media.ffmpeg.probe",
                        lambda *a, **k: {"format": {"duration": "8"},
                                         "streams": [{"codec_type": "audio"}]})
    real = {}

    def _extract(src, dst, *a, **k):
        from pathlib import Path as _P
        _P(dst).write_bytes(b"RIFF....")
        real["wav"] = str(dst)
        return _P(dst)

    monkeypatch.setattr("vii.media.ffmpeg.extract_audio_wav", _extract)

    class _Client:
        live = True

        def transcribe(self, path, language=None, **kw):
            from pathlib import Path as _P2
            assert _P2(path).exists()
            return {"sessionId": "s1", "transcript": "hello",
                    "audioDurationMs": 1000,
                    "turns": [{"turnId": 1, "startMs": 0, "endMs": 1000,
                               "transcript": "hello", "speaker": "A"}]}

    tr = transcribe_audio(tmp_path / "v.mp4", _s(tmp_path), _Client())
    assert len(tr.segments) == 1 and tr.segments[0].speaker == "A"
    assert tr.__dict__["_asr_session_ids"] == ["s1"]
    import os

    assert not os.path.exists(real["wav"])  # temp WAV cleaned up
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate

    svc = AnalysisService(_s(tmp_path, MODEL_API_KEY="k"))
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/v.mp4"}))
    from vii.persistence.repositories import AnalysisRepo

    with svc.Session() as db:
        repo = AnalysisRepo(db)
        for s_ in tr.segments:
            repo.add_transcript_segment(jid, s_.start_s, s_.end_s, s_.text,
                                        s_.speaker or "", tr.engine)
        segs = repo.segments_for_job(jid)
        assert len(segs) == 1 and segs[0].text == "hello"
