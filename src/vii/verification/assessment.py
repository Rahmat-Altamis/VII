"""Claim assessment with enforced evidence rules (Pydantic-validated).

Verdicts are stance-based: a source only counts for SUPPORTED when its
``relationship`` is ``supports`` and for CONTRADICTED when it is
``contradicts``, and a decisive verdict additionally requires the source
to be cited. Credibility tier alone never produces SUPPORTED. Provider
payloads that carry no stance at all fall back to the legacy cited +
high-tier rule so older transcripts remain assessable.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from vii.domain.enums import ClaimStatus
from vii.domain.schemas import ClaimAssessmentIn, ClaimIn, SearchResultItem
from vii.evidence.sources import credibility_tier
from vii.evidence.validation import validate as validate_evidence

# Fact-check outlets whose debunk verdicts flip an assessment. A result
# from one of these domains whose URL/title/snippet carries an explicit
# debunk signal counts as CONTRADICTS even when the provider supplied
# no stance, this stops "supported" from being awarded to hoax content
# merely because fact-checkers discuss (and refute) it.
_FACTCHECK_DOMAINS = (
    "factcheck.org", "fullfact.org", "snopes.com", "politifact.com",
    "factually.co", "reuters.com/fact-check", "apnews.com/hub/fact-check",
    "bbc.com/news/reality_check", "theferret.scot", "maldita.es",
    "correctiv.org/faktencheck",
)
_DEBUNK_RE = re.compile(
    r"\b(fake|falsely|false|debunk(?:ed|s|ing)?|dubious|hoax|fabricat\w+|"
    r"misattribut\w+|misleading|no-evidence|not-true|unproven|"
    r"missing-context|altered|manipulated)\b", re.I)

# Topical-relevance gate: a cited source only corroborates when it is
# actually about the claim. Without this, any retrieved page (a Ronaldo
# article, a Senate farewell address) could "support" an unrelated claim.
_STOPWORDS = frozenset(
    "the a an and or of to in on for with from that this it is was were are "
    "be been being has have had will would could should video shows shown "
    "says said displays presents pictured seen visible".split())
_WEASEL_RE = re.compile(
    r"\b(everybody|everyone|nobody|no one|all people|most people|"
    r"people (believe|think|say|know))\b.{0,40}"
    r"\b(believe[sd]?|think|thinks|thought|say|says|said|know[s]?|"
    r"agree[sd]?|claim[s]?)\b", re.I)


def _claim_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{4,}", text.lower())
            if t not in _STOPWORDS]


def _relevance(claim_text: str, r: SearchResultItem) -> tuple[int, float]:
    """(distinct token hits, hit ratio) of claim tokens in the result."""
    tokens = _claim_tokens(claim_text)
    if not tokens:
        return 0, 0.0
    blob = f"{r.url} {r.title} {r.snippet}".lower()
    hits = sum(1 for t in set(tokens) if t in blob)
    return hits, hits / len(set(tokens))


def _relevant(claim_text: str, r: SearchResultItem) -> bool:
    if not _claim_tokens(claim_text):
        return True  # degenerate claim: relevance cannot be judged
    hits, ratio = _relevance(claim_text, r)
    return hits >= 2 and ratio >= 0.25


def _debunk_hits(results: list[SearchResultItem]) -> list[SearchResultItem]:
    """Fact-check results that explicitly refute the claim's subject."""
    hits = []
    for r in results:
        host = urlparse(r.url).netloc.lower().removeprefix("www.")
        blob = f"{r.url} {r.title} {r.snippet}"
        if any(host == d.split("/")[0] or host.endswith("." + d.split("/")[0])
               for d in _FACTCHECK_DOMAINS) and _DEBUNK_RE.search(blob):
            hits.append(r)
    return hits


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
    real = [r for r in results if r.url.startswith(("http://", "https://"))]
    urls = [r.url for r in real]
    excerpts = [r.snippet for r in results if r.snippet][:5]
    cited_urls = {c.url for c in (citations or [])}
    supports = [r for r in real if r.relationship == "supports"]
    contradicts = [r for r in real if r.relationship == "contradicts"]
    # Fact-check debunks count as contradiction even with no provider
    # stance; the hoax case (factcheck.org "dubious-quote", fullfact
    # "quote-fake") must flip the verdict, not average away.
    debunks = _debunk_hits(real)
    contradicts = contradicts + [d for d in debunks if d not in contradicts]
    cited_supports = [r for r in supports if r.url in cited_urls
                      and _relevant(claim.text, r)]
    cited_contradicts = [r for r in contradicts if r.url in cited_urls]
    cited_debunks = [r for r in debunks if r.url in cited_urls]

    if cited_debunks:
        sources = ", ".join(sorted({urlparse(r.url).netloc for r in cited_debunks}))
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.CONTRADICTED,
            explanation=("Fact-checkers debunk the underlying assertion "
                         f"({sources}). The claim describes what the video "
                         "presents, not a verified fact."),
            evidence_urls=urls[:8], excerpts=excerpts,
            contradictions=f"Debunked by: {sources}.",
            confidence=0.8,
            limitations="Verdict follows fact-checker consensus; read the "
                        "cited fact-checks for full context.",
            method="meta_web_search")

    if supports and contradicts:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation="Supporting and contradicting sources were both retrieved.",
            evidence_urls=urls[:8], excerpts=excerpts,
            contradictions="Retrieved sources disagree on this claim.",
            confidence=0.45,
            limitations="Conflicting sources; independent review recommended.",
            method="meta_web_search")
    if contradicts:
        if cited_contradicts:
            return ClaimAssessmentIn(
                claim_id="", status=ClaimStatus.CONTRADICTED,
                explanation="Cited sources contradict the claim.",
                evidence_urls=urls[:8], excerpts=excerpts,
                contradictions="Cited evidence contradicts the claim.",
                confidence=0.75,
                limitations="Assessment reflects retrieved sources only.",
                method="meta_web_search")
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation="Contradicting sources retrieved but none were cited.",
            evidence_urls=urls[:8], excerpts=excerpts, confidence=0.4,
            limitations="Uncited contradicting evidence; further verification needed.",
            method="meta_web_search")
    if supports:
        if cited_supports:
            if _WEASEL_RE.search(claim.text):
                return ClaimAssessmentIn(
                    claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
                    explanation=("Unquantifiable belief claim ('everybody "
                                 "believes...'), no source can verify what "
                                 "everyone thinks, so it cannot be supported "
                                 "as stated."),
                    evidence_urls=urls[:8], excerpts=excerpts, confidence=0.4,
                    limitations="Rephrase as a checkable claim to verify it.",
                    method="meta_web_search")
            return ClaimAssessmentIn(
                claim_id="", status=ClaimStatus.SUPPORTED,
                explanation="Cited sources support the claim.",
                evidence_urls=urls[:8], excerpts=excerpts, confidence=0.75,
                limitations="Assessment reflects retrieved sources only.",
                method="meta_web_search")
        cited_but_irrelevant = [r for r in supports if r.url in cited_urls]
        if cited_but_irrelevant:
            return ClaimAssessmentIn(
                claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
                explanation="Cited sources are topically unrelated to the "
                            "claim, so they cannot corroborate it.",
                evidence_urls=urls[:8], excerpts=excerpts, confidence=0.35,
                limitations="Retrieved sources missed the claim's topic.",
                method="meta_web_search")
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation="Supporting sources retrieved but none were cited.",
            evidence_urls=urls[:8], excerpts=excerpts, confidence=0.4,
            limitations="Partial evidence; further verification needed.",
            method="meta_web_search")
    if contradiction_hint:
        return ClaimAssessmentIn(
            claim_id="", status=ClaimStatus.MIXED_EVIDENCE,
            explanation=f"Sources disagree on this claim: {contradiction_hint}",
            evidence_urls=urls[:8], excerpts=excerpts,
            contradictions=contradiction_hint, confidence=0.45,
            limitations="Conflicting sources; independent review recommended.",
            method="meta_web_search")
    # Legacy fallback only when no source carried any stance at all.
    relevant_cited = [r for r in real
                      if r.url in cited_urls and _relevant(claim.text, r)]
    if not any(r.relationship for r in real) and relevant_cited \
            and max((credibility_tier(r.url, r.title)
                     for r in relevant_cited), default=0) >= 2:
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
