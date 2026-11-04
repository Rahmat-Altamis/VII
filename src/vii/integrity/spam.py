"""Mass-produced spam pattern detection.

Some videos are not claims to verify but spam formats to recognize:
formulaic reddit-story readings, fake-chat skits, TTS-narrated scam
bait, watermark-per-clip repost farms. Per-claim verdicts on such
videos come back "mixed" forever, which hides the actual finding.

assess_spam combines cheap local signals (watermark changes across
clips, formulaic markers) with one hosted judgment over the summary +
transcript, and returns a spam probability with named signals. Never a
verdict, probabilistic evidence like ai_detection.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vii.meta.client import MetaClient

# Formulaic markers common in mass-produced storytime/spam videos.
FORMULA_MARKERS = (
    "part 1", "part 2", "follow for part", "like and subscribe",
    "comment below", "you won't believe", "what happened next",
    "storytime", "reddit story", "aita for",
)

PROMPT = """You classify videos as mass-produced spam or not. Mass-produced
spam means: formulaic repetitive format, text-to-speech or flat
narration reading a script, fake chat/story screenshots, engagement
bait (part 1, follow for more), rapidly reposted compilations with
changing watermarks. A genuine vlog, news clip, or creative short is
NOT spam even if low quality. Given the summary, transcript excerpt,
and claims below, return ONLY a JSON object:
{"spam_probability": 0.0-1.0, "signals": ["short signal", ...],
"format": "one-line format description"}"""


def local_signals(summary: str, transcript: str, claims: list[str]) -> list[str]:
    """Deterministic spam markers (no provider call)."""
    blob = f"{summary}\n{transcript}\n{' '.join(claims)}".lower()
    found = [f"formulaic marker: '{m}'"
             for m in FORMULA_MARKERS if m in blob]
    watermarks = set(re.findall(r"watermark[^:]*:\s*([a-z0-9_,\s]+)",
                                blob)) if "watermark" in blob else set()
    if watermarks:
        found.append("watermarks change across clips (repost compilation)")
    return found[:8]


def assess_spam(summary: str, transcript: str, claims: list[str],
                client: MetaClient | None, model: str) -> dict[str, Any]:
    """One hosted judgment + local signals. See module docstring."""
    found = local_signals(summary, transcript, claims)
    if client is None or not client.live:
        return {"status": "unavailable", "spam_probability": None,
                "signals": found,
                "note": "no live provider client; local signals only"}
    excerpt = transcript[:2000]
    claim_lines = "\n".join(f"- {c[:160]}" for c in claims[:15])
    payload = {"model": model,
               "input": [{"role": "user", "content": [{
                   "type": "input_text",
                   "text": f"{PROMPT}\n\nSUMMARY:\n{summary[:1500]}\n\n"
                           f"TRANSCRIPT EXCERPT:\n{excerpt}\n\nCLAIMS:\n"
                           f"{claim_lines}"}]}]}
    try:
        from vii.meta.response_parser import output_text

        resp = client.responses_create(payload)
        text = output_text(resp if isinstance(resp, dict) else {})
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        prob = float(parsed.get("spam_probability", 0) or 0)
        prob = min(1.0, max(0.0, prob))
        signals = [str(s) for s in (parsed.get("signals", []) or [])][:8]
        fmt = str(parsed.get("format", "") or "")
    except Exception as e:
        return {"status": "failed", "spam_probability": None,
                "signals": found,
                "note": f"hosted judgment failed: {type(e).__name__}: "
                        f"{str(e)[:200]}"}
    return {"status": "success", "spam_probability": round(prob, 3),
            "signals": found + [s for s in signals if s not in found][:8],
            "format": fmt,
            "note": "Probabilistic spam-format evidence, not a verdict."}
