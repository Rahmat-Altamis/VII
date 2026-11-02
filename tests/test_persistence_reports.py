"""Areas 16-17: database persistence + JSON/Markdown exports."""
from vii.application.services import AnalysisService
from vii.domain.schemas import AnalysisCreate
from vii.reports import exporter


def test_service_create_and_run_offline(settings):
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(source={"kind": "public_url",
                                            "url": "https://example.com/v.mp4"},
                                    title="t", offline=True))
    payload = svc.run(jid)
    assert payload["offline"] is True
    assert len(payload["claims"]) >= 3  # 2 factual + 1 opinion
    kinds = {c["status"] for c in payload["claims"]}
    assert "insufficient_evidence" in kinds or "unverifiable" in kinds
    d = svc.get(jid)
    assert d["status"] == "succeeded" and len(d["log"]) > 0


def test_reports_export(tmp_path):
    p = exporter.build_payload("job_x", "T", {"a": 1}, [], [], [], ["lim"], True)
    jp = exporter.export(p, tmp_path, "json")
    mp = exporter.export(p, tmp_path, "markdown")
    assert jp.exists() and mp.exists()
    md = mp.read_text()
    assert "SYNTHETIC DEMO" in md
