"""Areas 6, 8, 18-20: FFmpeg fallback, transcription adapter, FastAPI, Qt startup, offline E2E."""
import shutil
from pathlib import Path

import pytest


def test_ffprobe_on_missing_file_raises(tmp_path):
    from vii.media import ffmpeg as ff
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not installed")
    with pytest.raises(Exception):
        ff.probe(tmp_path / "nope.mp4")


def test_transcription_offline_unavailable(settings):
    from vii.meta.transcription import transcribe_audio
    tr = transcribe_audio("/nonexistent/x.mp4", settings, None)
    assert tr.offline and tr.segments == []


def test_fastapi_health_and_flow(settings, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import vii.api.routes as routes
    from vii.application.services import AnalysisService
    from vii.config import get_settings
    get_settings.cache_clear()
    routes._service = AnalysisService(settings)
    from vii.api.app import app
    c = TestClient(app)
    assert c.get("/health").json()["ok"] is True
    r = c.post("/analyses", json={"source": {"kind": "public_url",
                  "url": "https://example.com/v.mp4"}, "offline": True})
    assert r.status_code == 201
    jid = r.json()["job_id"]
    out = c.post(f"/analyses/{jid}/run").json()
    assert out["offline"] is True and len(out["claims"]) >= 3
    assert c.get(f"/analyses/{jid}").json()["status"] == "succeeded"
    import vii.api.routes as routes2
    exp = Path(settings.storage_dir) / "exports" / f"{jid}.md"
    assert exp.exists(), f"expected export at {exp}"
    assert "SYNTHETIC DEMO" in exp.read_text()


def test_qt_app_starts():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from vii.application.services import AnalysisService
    from vii.config import Settings
    import tempfile
    tmp = tempfile.mkdtemp()
    s = Settings(VII_OFFLINE_MODE=True, VII_DATABASE_URL=f"sqlite:///{tmp}/t.db",
                 VII_STORAGE_DIR=tmp)
    app = QApplication.instance() or QApplication([])
    from vii.ui.main_window import MainWindow
    w = MainWindow(AnalysisService(s))
    assert w.windowTitle().startswith("Video Integrity")
    w.close()


def test_offline_e2e_demo_flow(settings):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    payload = svc.run(jid)
    assert payload["dimensions"].keys() == {
        "claim_verification", "supporting_contradicting_evidence",
        "media_origin", "originality", "uncertainty_limitations"}
