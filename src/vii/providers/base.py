"""Shared provider contracts (reconstructed): dataclasses used by meta/mock providers.

These types predate the Pydantic domain layer in vii.domain.schemas. They are
kept for backward compatibility; new code should prefer the domain schemas.
Conversion helpers bridge the two worlds.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class UnderstandingResult:
    subject: str = ""
    events: list[str] = field(default_factory=list)
    narration: str = ""
    on_screen_text: str = ""
    ambiguities: list[str] = field(default_factory=list)
    method: str = ""


@dataclass
class ExtractedClaim:
    text: str = ""
    category: str = "factual"
    t_start: float = 0.0
    t_end: float = 0.0
    why_verifiable: str = ""
    uncertainty: str = ""


@dataclass
class RetrievedSource:
    title: str = ""
    publisher: str = ""
    url: str = ""
    published_at: str = ""
    excerpt: str = ""
    relation: str = ""  # supports | contradicts | context
    credibility_note: str = ""
    retrieval_method: str = ""


@dataclass
class ClaimVerdict:
    status: str = "insufficient"  # supported|contradicted|mixed|insufficient|unverifiable
    reasoning: str = ""
    evidence_indexes: list[int] = field(default_factory=list)
    method: str = ""


class Provider(Protocol):
    name: str

    def describe_video(self, context: dict) -> UnderstandingResult: ...
    def extract_claims(self, understanding: UnderstandingResult) -> list[ExtractedClaim]: ...
    def search_evidence(self, claim_text: str) -> list[RetrievedSource]: ...
    def verify_claim(self, claim_text: str, sources: list[RetrievedSource]) -> ClaimVerdict: ...


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", re.S)


def parse_json_block(raw: str):
    """Parse a JSON array/object from raw model text (fenced block or bare)."""
    text = raw.strip()
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(1))
    start_candidates = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    end_candidates = [i for i in (text.rfind("}"), text.rfind("]")) if i >= 0]
    if start_candidates and end_candidates:
        start, end = min(start_candidates), max(end_candidates)
        if end > start:
            return json.loads(text[start:end + 1])
    return json.loads(text)
