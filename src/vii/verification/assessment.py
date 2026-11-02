"""Claim assessment with enforced evidence rules (Pydantic-validated)."""
from __future__ import annotations

from vii.domain.enums import ClaimStatus
from vii.domain.schemas import ClaimAssessmentIn, ClaimIn, SearchResultItem
from vii.evidence.sources import credibility_tier
from vii.evidence.validation import validate as validate_evidence


def assess(claim: ClaimIn, results: list[SearchResultItem], citations,
           offline: bool, contradiction_hint: str = "") -> ClaimAssessmentIn:
    if offline or not results:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.INSUFFICIENT_EVIDENCE,
            explanation=("No live web search was performed (synthetic demo mode "
                         "or search unavailable), so this claim could not be "
                         "checked against external sources."),
            limitations="No external evidence retrieved; transcript/video only.",
            method="no_search_performed")
    v = validate_evidence(results, citations)
    urls = [r.url for r in results if r.url.startswith(("http://", "https://"))]
    excerpts = [r.snippet for r in results if r.snippet][:5]
    tiers = [credibility_tier(r.url, r.title) for r in results]
    if contradiction_hint:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation=f"Sources disagree on this claim: {contradiction_hint}",
            evidence_urls=urls[:8], excerpts=excerpts,
            contradictions=contradiction_hint, confidence=0.45,
            limitations="Conflicting sources; independent review recommended.",
            method="meta_web_search")
    if v["cited"] and max(tiers, default=0) >= 2:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.SUPPORTED,
            explanation="Cited high-credibility sources corroborate the claim.",
            evidence_urls=urls[:8], excerpts=excerpts, confidence=0.75,
            limitations="Assessment reflects retrieved sources only.",
            method="meta_web_search")
    if v["has_evidence"]:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation="Some sources retrieved but corroboration is partial or uncited.",
            evidence_urls=urls[:8], excerpts=excerpts, confidence=0.4,
            limitations="Partial evidence; further verification needed.",
            method="meta_web_search")
    return ClaimAssessmentIn(
        claim_id="", status=ClaimStatus.INSUFFICIENT_EVIDENCE,
        explanation="Web search returned no usable sources for this claim.",
        limitations="No retrievable evidence.", method="meta_web_search")
