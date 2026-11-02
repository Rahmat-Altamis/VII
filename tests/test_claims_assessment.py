"""Areas 12-15: claim extraction/classification + assessment constraints."""
import pytest

from vii.domain.enums import ClaimKind, ClaimStatus
from vii.domain.schemas import ClaimAssessmentIn, ClaimIn
from vii.verification import assessment as amod
from vii.verification import claims as cmod


def _vu(texts):
    from vii.meta import response_parser as rp
    import json as _json
    return rp.parse_video_json(_json.dumps({"summary": "s", "factual_claims": [
        {"text": t} for t in texts]}))


def test_opinion_not_factual():
    claims = cmod.extract(_vu(["I think this is the best video ever"]))
    assert claims and claims[0].kind == ClaimKind.OPINION


def test_factual_claim_extracted():
    claims = cmod.extract(_vu(["The Eiffel Tower is 330 metres tall."]))
    assert claims[0].kind == ClaimKind.FACTUAL


def test_supported_requires_evidence_and_explanation():
    with pytest.raises(Exception):
        ClaimAssessmentIn(claim_id="c1", status=ClaimStatus.SUPPORTED,
                          explanation="", evidence_urls=[])
    with pytest.raises(Exception):
        ClaimAssessmentIn(claim_id="c1", status=ClaimStatus.SUPPORTED,
                          explanation="ok", evidence_urls=[])


def test_offline_assessment_is_insufficient():
    a = amod.assess(ClaimIn(text="X"), [], [], offline=True)
    assert a.status == ClaimStatus.INSUFFICIENT_EVIDENCE
    assert "No live web search" in a.explanation
    assert a.method == "no_search_performed"


def test_conflicting_evidence_mixed():
    from vii.domain.schemas import SearchResultItem
    r = [SearchResultItem(url="https://example.com/a", snippet="yes")]
    a = amod.assess(ClaimIn(text="X"), r, [], offline=False, contradiction_hint="A says yes, B says no")
    assert a.status == ClaimStatus.MIXED_EVIDENCE
