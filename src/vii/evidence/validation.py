"""Evidence validation: real records, citation relationships, conflict flags."""
from __future__ import annotations

from vii.domain.schemas import CitationAnnotation, SearchResultItem


def validate(results: list[SearchResultItem], citations: list[CitationAnnotation]) -> dict:
    real = [r for r in results if r.url.startswith(("http://", "https://"))]
    cited_urls = {c.url for c in citations}
    cited = [r for r in real if r.url in cited_urls]
    uncited = [r for r in real if r.url not in cited_urls]
    orphan = [c for c in citations if c.url not in {r.url for r in real}]
    return {
        "retrieved": len(results), "real": len(real),
        "cited": len(cited), "uncited": len(uncited),
        "orphan_citations": len(orphan),
        "has_evidence": bool(real),
        "note": ("cited" if cited else "retrieved-but-uncited") if real else "no-evidence",
    }
