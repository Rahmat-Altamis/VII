"""Phase 1 (handoff): verdict stance, evidence fields, classifier, duration,
terminal guard. Fake transports only, no live provider calls."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from vii.domain.enums import ClaimKind, ClaimStatus
from vii.domain.schemas import ClaimIn, SearchResultItem
from vii.verification import assessment as amod
from vii.verification import claims as cmod


def _vu(texts):
    import json as _json

    from vii.meta import response_parser as rp
    return rp.parse_video_json(_json.dumps({"summary": "s", "factual_claims": [
        {"text": t} for t in texts]}))


def _item(url, relationship="", snippet="evidence", title="Source"):
    return SearchResultItem(url=url, title=title, snippet=snippet,
                            relationship=relationship)


def _cit(url):
    from vii.domain.schemas import CitationAnnotation
    return CitationAnnotation(url=url, title="Source", claim_ids=["c1"])


# -- verdict logic: real CONTRADICTED path, stance-based SUPPORTED ---------

def test_contradicted_when_only_contradicting_cited_evidence():
    r = [_item("https://www.nasa.gov/a", relationship="contradicts")]
    a = amod.assess(ClaimIn(text="X happened"), r, [_cit(r[0].url)], offline=False)
    assert a.status == ClaimStatus.CONTRADICTED
    assert a.evidence_urls


def test_mixed_when_supporting_and_contradicting_evidence():
    r = [_item("https://www.nasa.gov/a", relationship="supports"),
         _item("https://www.bbc.com/b", relationship="contradicts")]
    a = amod.assess(ClaimIn(text="X"), r, [_cit(r[0].url), _cit(r[1].url)],
                    offline=False)
    assert a.status == ClaimStatus.MIXED_EVIDENCE


def test_supported_requires_supporting_stance_not_just_high_tier_citation():
    # Cited official source with no supporting stance must not be SUPPORTED.
    r = [_item("https://www.nasa.gov/a", relationship="context")]
    a = amod.assess(ClaimIn(text="X"), r, [_cit(r[0].url)], offline=False)
    assert a.status != ClaimStatus.SUPPORTED


def test_supported_with_supporting_cited_evidence():
    r = [_item("https://example.com/a", relationship="supports")]
    a = amod.assess(ClaimIn(text="X"), r, [_cit(r[0].url)], offline=False)
    assert a.status == ClaimStatus.SUPPORTED


def test_supporting_but_uncited_is_not_supported():
    r = [_item("https://example.com/a", relationship="supports")]
    a = amod.assess(ClaimIn(text="X"), r, [], offline=False)
    assert a.status != ClaimStatus.SUPPORTED


# -- evidence fields --------------------------------------------------------

def test_search_result_item_carries_relationship_and_dates():
    it = SearchResultItem(url="https://example.com/a", relationship="supports",
                          publication_date="2024-01-15")
    assert it.relationship == "supports"
    assert it.publication_date == "2024-01-15"
    assert it.retrieved_at is not None


def test_parser_carries_relationship_and_publication_date():
    from vii.meta import response_parser as rp
    resp = {"id": "r1", "output": [
        {"type": "web_search_call", "id": "ws_1", "results": [
            {"url": "https://example.com/a", "title": "A", "snippet": "s",
             "relationship": "contradicts", "publication_date": "2024-02-01"}]}]}
    items = rp.parse_search_results(resp)
    assert items[0].relationship == "contradicts"
    assert items[0].publication_date == "2024-02-01"
    assert items[0].retrieved_at is not None


# -- classifier: will/should/best must not misclassify factual claims -------

@pytest.mark.parametrize("text", [
    "Water will boil at 100 degrees Celsius at sea level.",
    "The dosage should be 5 mg twice daily.",
    "The Eiffel Tower is 330 metres tall.",
])
def test_factual_claims_with_will_should_stay_factual(text):
    claims = cmod.extract(_vu([text]))
    assert claims[0].kind == ClaimKind.FACTUAL


def test_opinion_still_detected():
    claims = cmod.extract(_vu(["I think this is the best video ever"]))
    assert claims[0].kind == ClaimKind.OPINION


def test_explicit_prediction_still_detected():
    claims = cmod.extract(_vu(["Analysts forecast rain by 2030."]))
    assert claims[0].kind == ClaimKind.PREDICTION


# -- fail-closed duration at the pipeline boundary --------------------------

def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _make_mp4(path: Path, duration_s: float | None = 5.0) -> Path:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 0x200) + b"isomiso2")
    if duration_s is None:
        path.write_bytes(ftyp + _box(b"mdat", b"\x00" * 16))
    else:
        mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(
            ">IIII", 0, 0, 1000, int(duration_s * 1000)))
        path.write_bytes(ftyp + _box(b"moov", mvhd) + _box(b"mdat", b"\x00" * 16))
    return path


def test_pipeline_rejects_local_media_with_unknown_duration(settings, tmp_path):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate
    media = _make_mp4(tmp_path / "nodur.mp4", duration_s=None)
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "local_file", "local_path": str(media)}, demo=True))
    with pytest.raises(ValueError):
        svc.run(jid)
    assert svc.get(jid)["status"] == "failed"


# -- terminal-state guard -----------------------------------------------------

def test_cancelled_job_is_not_rerun_or_overwritten(settings):
    from vii.application.services import AnalysisService
    from vii.domain.enums import JobStatus
    from vii.domain.schemas import AnalysisCreate
    from vii.persistence.repositories import JobRepo
    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    with svc.Session() as db:
        repo = JobRepo(db)
        repo.set_status(repo.get(jid), JobStatus.CANCELLED)
    with pytest.raises(RuntimeError):
        svc.run(jid)
    with svc.Session() as db:
        assert str(JobRepo(db).get(jid).status) == "cancelled"
