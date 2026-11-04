"""Areas 12-15: claim extraction/classification + assessment constraints."""
import pytest
from pydantic import ValidationError

from vii.domain.enums import ClaimKind, ClaimStatus
from vii.domain.schemas import ClaimAssessmentIn, ClaimIn
from vii.verification import assessment as amod
from vii.verification import claims as cmod


def _vu(texts):
    import json as _json

    from vii.meta import response_parser as rp
    return rp.parse_video_json(_json.dumps({"summary": "s", "factual_claims": [
        {"text": t} for t in texts]}))


def test_opinion_not_factual():
    claims = cmod.extract(_vu(["I think this is the best video ever"]))
    assert claims and claims[0].kind == ClaimKind.OPINION


def test_factual_claim_extracted():
    claims = cmod.extract(_vu(["The Eiffel Tower is 330 metres tall."]))
    assert claims[0].kind == ClaimKind.FACTUAL


def test_supported_requires_evidence_and_explanation():
    with pytest.raises(ValidationError):
        ClaimAssessmentIn(claim_id="c1", status=ClaimStatus.SUPPORTED,
                          explanation="", evidence_urls=[])
    with pytest.raises(ValidationError):
        ClaimAssessmentIn(claim_id="c1", status=ClaimStatus.SUPPORTED,
                          explanation="ok", evidence_urls=[])


def test_offline_assessment_is_insufficient():
    a = amod.assess(ClaimIn(text="X"), [], [], offline=True)
    assert a.status == ClaimStatus.INSUFFICIENT_EVIDENCE
    assert "No live web search" in a.explanation
    assert a.method == "no_search_performed"


def test_factcheck_debunk_flips_verdict_to_contradicted():
    from vii.domain.schemas import CitationAnnotation, SearchResultItem
    r = [SearchResultItem(url="https://www.factcheck.org/2019/12/dubious-quote-attributed-to-trumps-mother/",
                          title="Dubious Quote Attributed to Trump's Mother",
                          snippet="Viral quote is fabricated."),
         SearchResultItem(url="https://fullfact.org/us/trump-mother-quote-fake-reshared/",
                          title="Trump mother quote fake reshared", snippet="False.")]
    c = [CitationAnnotation(url=r[0].url, title="f", claim_ids=["c"]),
         CitationAnnotation(url=r[1].url, title="f", claim_ids=["c"])]
    a = amod.assess(ClaimIn(text="The video attributes the quote to Mary Anne Trump"),
                    r, c, offline=False)
    assert a.status == ClaimStatus.CONTRADICTED
    assert "debunk" in a.explanation.lower()


def test_factcheck_without_debunk_signal_does_not_flip():
    from vii.domain.schemas import CitationAnnotation, SearchResultItem
    r = [SearchResultItem(url="https://www.factcheck.org/2024/01/budget-vote-timeline/",
                          title="Budget vote timeline", snippet="What happened.")]
    c = [CitationAnnotation(url=r[0].url, title="f", claim_ids=["c"])]
    a = amod.assess(ClaimIn(text="The budget vote happened in January."), r, c, offline=False)
    assert a.status != ClaimStatus.CONTRADICTED


def test_uncited_debunk_is_mixed_not_contradicted():
    from vii.domain.schemas import SearchResultItem
    r = [SearchResultItem(url="https://www.snopes.com/fact-check/viral-hoax-claim/",
                          title="Viral hoax claim", snippet="This is a hoax.")]
    a = amod.assess(ClaimIn(text="The video makes the viral claim."), r, [], offline=False)
    assert a.status == ClaimStatus.MIXED_EVIDENCE


def test_irrelevant_cited_sources_cannot_support():
    from vii.domain.schemas import CitationAnnotation, SearchResultItem
    r = [SearchResultItem(url="http://example.com/news/ronaldos-legacy-untouchable",
                          title="Ronaldo's legacy is untouchable",
                          snippet="Thierry Henry after Portugal exit.",
                          relationship="supports")]
    c = [CitationAnnotation(url=r[0].url, title="x", claim_ids=["c"])]
    a = amod.assess(ClaimIn(text="Everybody believes the exit was for the last time."),
                    r, c, offline=False)
    assert a.status == ClaimStatus.MIXED_EVIDENCE
    assert "unrelated" in a.explanation


def test_relevant_cited_source_still_supports():
    from vii.domain.schemas import CitationAnnotation, SearchResultItem
    r = [SearchResultItem(url="https://www.reuters.com/sport/daniel-ricciardo-f1-exit",
                          title="Daniel Ricciardo exits Formula 1 paddock",
                          snippet="Daniel Ricciardo leaves the F1 paddock.")]
    c = [CitationAnnotation(url=r[0].url, title="x", claim_ids=["c"])]
    a = amod.assess(ClaimIn(text="Daniel Ricciardo exited the F1 paddock."),
                    r, c, offline=False)
    assert a.status == ClaimStatus.SUPPORTED


def test_conflicting_evidence_mixed():
    from vii.domain.schemas import SearchResultItem
    r = [SearchResultItem(url="https://example.com/a", snippet="yes")]
    a = amod.assess(ClaimIn(text="X"), r, [], offline=False, contradiction_hint="A says yes, B says no")
    assert a.status == ClaimStatus.MIXED_EVIDENCE
