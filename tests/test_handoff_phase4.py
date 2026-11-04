"""Phase 4 (handoff): VideoChecker wrapper, vii check --json contract,
interactive terminal follow-ups, SHA-256 caching. Fake/demo only."""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _make_mp4(path: Path) -> Path:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1000, 5000))
    path.write_bytes(ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16))
    return path


def test_videochecker_exported_without_ui():
    import vii
    assert "VideoChecker" in vii.__all__
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'src'); "
         "from vii import VideoChecker; import vii.cli; "
         "assert 'PySide6' not in sys.modules; "
         "assert 'vii.ui' not in sys.modules; print('ok')"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_check_caches_by_sha256_and_never_rebills(settings, tmp_path, monkeypatch):
    import vii.client as client_mod
    from vii import VideoChecker
    calls = {"n": 0}
    real = client_mod.VII.analyze

    def counting(self, source, **kw):
        calls["n"] += 1
        return real(self, source, **kw)

    monkeypatch.setattr(client_mod.VII, "analyze", counting)
    media = _make_mp4(tmp_path / "clip.mp4")
    checker = VideoChecker(settings=settings)
    first = checker.check(str(media), demo=True)
    second = checker.check(str(media), demo=True)
    assert calls["n"] == 1  # second run served from SHA-256 cache
    assert first["job_id"] == second["job_id"]


def test_follow_up_answers_from_stored_report_without_provider(settings, tmp_path):
    from vii import VideoChecker
    media = _make_mp4(tmp_path / "clip.mp4")
    checker = VideoChecker(settings=settings)
    report = checker.check(str(media), demo=True)
    answer = checker.follow_up(report, "claims")
    assert "Eiffel Tower" in answer
    answer2 = checker.follow_up(report, "supported claims")
    assert isinstance(answer2, str) and answer2


def test_cli_check_json_one_object_and_exit_codes(settings, capsys):
    from vii import cli
    code = cli.main(["check", "https://example.com/demo.mp4", "--json"],
                    settings=settings)
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)  # exactly one JSON object on stdout
    assert payload["claims"]


def test_cli_check_exit_code_3_without_key(tmp_path, capsys):
    from vii import cli
    from vii.config import Settings
    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                 VII_STORAGE_DIR=tmp_path)
    code = cli.main(["check", "https://example.com/v.mp4", "--json"], settings=s)
    out = json.loads(capsys.readouterr().out)
    assert code == 3
    assert out["ok"] is False


def test_cli_check_exit_code_2_for_missing_file(settings, capsys):
    from vii import cli
    code = cli.main(["check", "/nonexistent/missing.mp4", "--json"],
                    settings=settings)
    json.loads(capsys.readouterr().out)
    assert code == 2


def test_interactive_followups_use_stored_report(settings, capsys, monkeypatch):
    from vii import cli
    answers = iter(["https://example.com/demo.mp4", "claims", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code = cli.main([], settings=settings)
    out = capsys.readouterr().out
    assert code == 0
    assert "Eiffel Tower" in out
