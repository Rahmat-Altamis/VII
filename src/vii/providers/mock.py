"""Deterministic mock provider for offline dev and tests. All outputs labeled mock."""
from __future__ import annotations

from .base import (
    ClaimVerdict,
    ExtractedClaim,
    Provider,
    RetrievedSource,
    UnderstandingResult,
)

MOCK_CORPUS = [
    {
        "title": "Mock Reference: Eiffel Tower facts",
        "publisher": "Mock Test Corpus",
        "url": "mock://corpus/eiffel-tower",
        "published_at": "2024-01-15",
        "excerpt": "The Eiffel Tower in Paris was completed in 1889 and stands about 330 metres tall.",
        "credibility_note": "Bundled deterministic test fixture; NOT internet evidence.",
    },
    {
        "title": "Mock Reference: Water boiling point",
        "publisher": "Mock Test Corpus",
        "url": "mock://corpus/boiling-point",
        "published_at": "2024-02-01",
        "excerpt": "Pure water boils at 100°C at standard atmospheric pressure (101.325 kPa).",
        "credibility_note": "Bundled deterministic test fixture; NOT internet evidence.",
    },
    {
        "title": "Mock Reference: Mars exploration",
        "publisher": "Mock Test Corpus",
        "url": "mock://corpus/mars",
        "published_at": "2024-03-10",
        "excerpt": "Multiple rovers, including Perseverance (landed 2021), have explored Mars.",
        "credibility_note": "Bundled deterministic test fixture; NOT internet evidence.",
    },
]


class MockProvider:
    name = "mock"

    def __init__(self, corpus: list[dict] | None = None) -> None:
        self.corpus = corpus if corpus is not None else MOCK_CORPUS

    def describe_video(self, context: dict) -> UnderstandingResult:
        name = str(context.get("file_name", "video"))
        duration = float(context.get("duration_s", 0.0) or 0.0)
        n_frames = int(context.get("n_frames", 0) or 0)
        return UnderstandingResult(
            subject=f"Offline mock description of {name}",
            events=[f"Analyzed {n_frames} sampled frame(s) across {duration:.1f}s (mock)."],
            narration="Mock narration: no speech recognition in offline mode.",
            on_screen_text="",
            ambiguities=["Synthetic mock: no live model viewed this video; claims below are deterministic fixtures."],
            method="mock frame-and-metadata fallback (explicitly labeled, NOT a live model)",
        )

    def extract_claims(self, understanding: UnderstandingResult) -> list[ExtractedClaim]:
        return [
            ExtractedClaim(
                text="The Eiffel Tower in Paris was completed in 1889.",
                category="factual",
                t_start=0.0,
                t_end=5.0,
                why_verifiable="Checkable against historical construction records.",
                uncertainty="Mock claim fixture; verify against live evidence before trusting.",
            ),
            ExtractedClaim(
                text="Pure water boils at 100°C at standard atmospheric pressure.",
                category="factual",
                t_start=5.0,
                t_end=10.0,
                why_verifiable="Checkable against physics references.",
                uncertainty="Mock claim fixture; precision depends on stated conditions.",
            ),
        ]

    def _score(self, claim_text: str, doc: dict) -> int:
        words = [w.strip(".,;:()\"'").lower() for w in claim_text.split() if len(w) > 3]
        hay = f"{doc['title']} {doc['excerpt']}".lower()
        return sum(1 for w in words if w in hay)

    def search_evidence(self, claim_text: str) -> list[RetrievedSource]:
        ranked = sorted(
            ((self._score(claim_text, d), d) for d in self.corpus),
            key=lambda t: t[0],
            reverse=True,
        )
        out: list[RetrievedSource] = []
        for score, doc in ranked:
            if score <= 0:
                continue
            out.append(
                RetrievedSource(
                    title=doc["title"],
                    publisher=doc.get("publisher", ""),
                    url=doc.get("url", ""),
                    published_at=doc.get("published_at", ""),
                    excerpt=doc.get("excerpt", ""),
                    relation="supports",
                    credibility_note=doc.get("credibility_note", ""),
                    retrieval_method="mock-corpus-keyword-match (offline fixture)",
                )
            )
        return out

    def verify_claim(self, claim_text: str, sources: list[RetrievedSource]) -> ClaimVerdict:
        if not sources:
            return ClaimVerdict(
                status="insufficient",
                reasoning="No sources were retrieved for this claim, so nothing supports or contradicts it.",
                evidence_indexes=[],
                method="mock rules: no-evidence -> insufficient",
            )
        supports = [s for s in sources if s.relation == "supports"]
        contradicts = [s for s in sources if s.relation == "contradicts"]
        if supports and contradicts:
            idx = [i for i, s in enumerate(sources) if s.relation in ("supports", "contradicts")]
            return ClaimVerdict(
                status="mixed",
                reasoning="Retrieved sources disagree; see supporting and contradicting excerpts.",
                evidence_indexes=idx,
                method="mock rules: both relations present -> mixed",
            )
        if contradicts:
            idx = [i for i, s in enumerate(sources) if s.relation == "contradicts"]
            return ClaimVerdict(
                status="contradicted",
                reasoning="Retrieved source(s) contradict the claim; see excerpts.",
                evidence_indexes=idx,
                method="mock rules: contradicting source -> contradicted",
            )
        idx = list(range(len(supports))) if supports else list(range(len(sources)))
        return ClaimVerdict(
            status="supported",
            reasoning="Retrieved mock-corpus source(s) support the claim. Fixture evidence only.",
            evidence_indexes=idx,
            method="mock rules: supporting source -> supported",
        )


def get_provider(name: str, **kwargs) -> Provider:
    from .meta import MetaProvider  # lazy: avoids httpx import cost for mock-only runs

    if name == "mock":
        return MockProvider(**kwargs)
    if name == "meta":
        return MetaProvider(**kwargs)
    raise ValueError(f"unknown provider: {name}")
