"""Atomic factual-claim extraction; separates fact from opinion/satire/etc."""
from __future__ import annotations

import re

from vii.domain.enums import ClaimKind
from vii.domain.schemas import ClaimIn, VideoUnderstanding

_OPINION = re.compile(r"\b(i think|i believe|in my opinion|should|best|worst|amazing|terrible)\b", re.I)
_PREDICTION = re.compile(r"\b(will|going to|predict|forecast|by 20\d\d)\b", re.I)
_SATIRE = re.compile(r"\b(satire|parody|joke|skit|comedy sketch)\b", re.I)


def classify(text: str) -> ClaimKind:
    t = text.strip()
    if _SATIRE.search(t): return ClaimKind.SATIRE
    if _OPINION.search(t): return ClaimKind.OPINION
    if _PREDICTION.search(t): return ClaimKind.PREDICTION
    if t.endswith("?"): return ClaimKind.SUBJECTIVE
    return ClaimKind.FACTUAL


def extract(vu: VideoUnderstanding) -> list[ClaimIn]:
    out: list[ClaimIn] = []
    for c in vu.__dict__.get("_claims", []):
        text = str(c.get("text", "")).strip()
        if not text:
            continue
        try:
            start = float(c["start_s"]) if c.get("start_s") is not None else None
        except (TypeError, ValueError): start = None
        try:
            end = float(c["end_s"]) if c.get("end_s") is not None else None
        except (TypeError, ValueError): end = None
        out.append(ClaimIn(text=text[:2000], kind=classify(text), start_s=start, end_s=end))
    # Fallback: split summary sentences when model returned no structured claims.
    if not out and vu.summary:
        for sent in re.split(r"(?<=[.!?])\s+", vu.summary.strip())[:10]:
            if len(sent) > 20:
                out.append(ClaimIn(text=sent[:2000], kind=classify(sent)))
    # Only factual claims go to verification; others are recorded as-is.
    return out
