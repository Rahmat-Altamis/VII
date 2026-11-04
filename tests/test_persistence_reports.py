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


def _claim(**kw):
    base = {"text": "The video says X.", "status": "supported",
            "confidence": 0.75, "explanation": "Sources agree.",
            "contradictions": "", "evidence": ["https://example.com/a"],
            "excerpts": ["X confirmed by reporting."]}
    base.update(kw)
    return base


def test_verdict_story_supported_covers_claim_vs_reality():
    story = exporter.verdict_story(_claim())
    for section in ("WHAT THE VIDEO SAYS", "EVIDENCE FOUND", "REALITY CHECK",
                    "STRONGEST EXCERPT", "KEY SOURCES", "WHY THIS VERDICT"):
        assert section in story
    assert "holds up" in story
    assert "https://example.com/a" in story


def test_verdict_story_contradicted_names_refutation():
    story = exporter.verdict_story(_claim(
        status="contradicted", confidence=0.8,
        contradictions="Debunked by: fullfact.org."))
    assert "does not hold up" in story
    assert "Debunked by: fullfact.org." in story


def test_verdict_story_never_invents_evidence():
    story = exporter.verdict_story(_claim(
        status="insufficient_evidence", confidence=0.0, evidence=[],
        excerpts=[], explanation="No usable sources."))
    assert "0 source(s)" in story
    assert "KEY SOURCES" not in story
    assert "STRONGEST EXCERPT" not in story


def test_markdown_uses_narratives(tmp_path):
    p = exporter.build_payload("job_x", "T", {"a": 1}, [_claim()], [], [],
                               ["lim"], False)
    mp = exporter.export(p, tmp_path, "markdown")
    md = mp.read_text()
    assert "WHAT THE VIDEO SAYS" in md and "REALITY CHECK" in md
