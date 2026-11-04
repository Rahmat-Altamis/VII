"""Slash-command TUI: session options delegate to existing tools."""
from __future__ import annotations


def _settings(tmp_path):
    from vii.config import Settings
    return Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                    VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                    VII_STORAGE_DIR=tmp_path, VII_DEMO_MODE=True)


def test_mode_output_ai_session_options(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    session = Session()
    assert handle("/mode demo", session, s) is None and session.demo is True
    assert handle("/output json", session, s) is None and session.as_json is True
    assert handle("/ai on 3", session, s) is None
    assert (session.ai_on, session.ai_samples) == (True, 3)
    out = capsys.readouterr().out
    assert "mode: demo" in out and "ai: on samples=3" in out


def test_help_and_unknown_and_quit(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    assert handle("/help", Session(), s) is None
    assert handle("/nope", Session(), s) is None
    assert handle("/quit", Session(), s) == 0
    out = capsys.readouterr().out
    assert "/key" in out and "unknown command" in out


def test_key_status_never_prints_secret(tmp_path, capsys):
    from vii.config import Settings
    from vii.tui import Session, handle

    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                 VII_STORAGE_DIR=tmp_path, MODEL_API_KEY="env-secret-123")
    assert handle("/key status", Session(), s) is None
    out = capsys.readouterr().out
    assert "env-secret-123" not in out and "source: env" in out


def test_plain_test_word_chats_instead_of_error(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    assert handle("test", Session(), s) is None
    out = capsys.readouterr().out
    assert "Hey!" in out and "file not found" not in out


def test_failed_check_stays_in_session(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    assert handle("/check /nonexistent/missing.mp4", Session(), s) is None


def test_chat_mode_words_toggle_session(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    session = Session()
    assert handle("switch to demo mode", session, s) is None
    assert session.demo is True
    assert handle("switch to live mode", session, s) is None
    assert session.demo is False
    assert handle("turn ai on", session, s) is None
    assert session.ai_on is True


def test_chat_fuzzy_check_runs_demo_video(tmp_path, capsys, monkeypatch):
    import vii.tui as tui_mod
    from vii.tui import Session, handle

    fake = tmp_path / "hoax video.mp4"
    fake.write_bytes(b"x")
    monkeypatch.setattr(tui_mod, "find_videos", lambda d=None: [fake])
    s = _settings(tmp_path)
    session = Session(demo=True)
    session.video_pick = [str(fake)]
    assert handle("check the hoax video", session, s) is None
    out = capsys.readouterr().out
    assert "Checking" in out and "hoax video.mp4" in out


def test_summary_plain_language_and_details_on_demand(tmp_path, capsys):
    from vii.tui import Session, print_details, print_summary

    report = {"claims": [
        {"text": "The video says X.", "status": "contradicted",
         "confidence": 0.8, "explanation": "Fact-checkers debunk it.",
         "contradictions": "Debunked by: fullfact.org.",
         "evidence": ["https://fullfact.org/x"], "excerpts": []},
        {"text": "The sky is blue.", "status": "supported",
         "confidence": 0.75, "explanation": "Sources agree.",
         "contradictions": "", "evidence": ["https://example.com/a"],
         "excerpts": []}]}
    print_summary(report)
    out = capsys.readouterr().out
    assert "1 claim(s) look FALSE" in out
    assert "https://fullfact.org/x" not in out  # details stay hidden
    session = Session(report=report)
    assert print_details("details 1", session) is True
    out = capsys.readouterr().out
    assert "REALITY CHECK" in out and "fullfact.org" in out
    assert print_details("claims", session) is False


def test_folder_command_sets_media_dir(tmp_path, capsys):
    from vii.tui import Session, handle, media_folder

    s = _settings(tmp_path)
    session = Session()
    assert handle(f"/folder {tmp_path}", session, s) is None
    assert session.media_dir == str(tmp_path)
    assert media_folder(session, s) == str(tmp_path)
    assert handle("/folder /nonexistent/dir", session, s) is None
    assert session.media_dir == str(tmp_path)  # unchanged
    assert "Media folder:" in capsys.readouterr().out


def test_chat_uses_custom_folder(tmp_path, capsys):
    from vii.tui import Session, handle

    (tmp_path / "mine.mp4").write_bytes(b"x")
    s = _settings(tmp_path)
    session = Session(media_dir=str(tmp_path))
    assert handle("list videos", session, s) is None
    out = capsys.readouterr().out
    assert "mine.mp4" in out


def test_chat_llm_discusses_and_falls_back(tmp_path, capsys, monkeypatch):
    import vii.tui as tui_mod
    from vii.config import Settings
    from vii.tui import Session, chat_llm

    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                 VII_STORAGE_DIR=tmp_path, MODEL_API_KEY="k")

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def responses_create(self, payload):
            assert "User says: is it a hoax?" in str(payload)
            return {"id": "r", "output": [
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": "Based on the report, it looks like a hoax."}]}]}

    monkeypatch.setattr("vii.meta.client.MetaClient", _FakeClient)
    monkeypatch.setattr(tui_mod, "find_videos", lambda d=None: [])
    assert chat_llm("is it a hoax?", Session(), s) is True
    assert "hoax" in capsys.readouterr().out

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def responses_create(self, payload):
            raise RuntimeError("down")

    monkeypatch.setattr("vii.meta.client.MetaClient", _Boom)
    assert chat_llm("hello?", Session(), s) is False
    assert chat_llm("hello?", Session(demo=True), s) is False


def test_status_line_shows_model_folder_mode(tmp_path):
    from vii.tui import Session, status_line

    s = _settings(tmp_path)
    line = status_line(Session(demo=True), s)
    assert "muse-spark-1.3" in line and "demo" in line


def test_quick_look_returns_in_seconds(tmp_path):
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        import pytest

        pytest.skip("ffmpeg not installed")
    from vii import VII

    src = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=black:size=64x64:duration=1",
                    str(src)], check=True, timeout=60)
    s = _settings(tmp_path)
    out = VII(settings=s).quick_look(src)
    assert out["file_name"] == "tiny.mp4"
    assert out["forensics"]["status"]
    assert out["elapsed_s"] < 10
    assert out["sha256"]


def test_cli_quick_flag(tmp_path, capsys):
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        import pytest

        pytest.skip("ffmpeg not installed")
    from vii.cli import main

    src = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=black:size=64x64:duration=1",
                    str(src)], check=True, timeout=60)
    assert main(["check", str(src), "--quick"],
                settings=_settings(tmp_path)) == 0
    assert "Fast screen" in capsys.readouterr().out


def test_demo_check_through_tui_keeps_report(tmp_path, capsys):
    from vii.tui import Session, handle

    s = _settings(tmp_path)
    session = Session(demo=True)
    assert handle("/check https://example.com/demo.mp4", session, s) is None
    assert session.report is not None
    assert handle("claims", session, s) is None  # follow-up, no re-check
    assert "Eiffel Tower" in capsys.readouterr().out
