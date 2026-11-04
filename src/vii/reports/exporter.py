"""JSON + Markdown report export. Five dimensions kept separate."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

DIMENSIONS = ["claim_verification", "supporting_contradicting_evidence",
              "media_origin", "originality", "uncertainty_limitations"]

_STATUS_LINE = {
    "supported": "the available evidence backs it",
    "contradicted": "the available evidence refutes it",
    "mixed_evidence": "the evidence is split or only partly corroborates it",
    "insufficient_evidence": "no usable evidence could be retrieved for it",
    "unverifiable": "it is not a factual claim and cannot be checked against evidence",
    "not_yet_analyzed": "it has not been analyzed yet",
}


def verdict_story(claim: dict) -> str:
    """Detailed claim-vs-reality paragraph for one assessed claim.

    Deterministic template over the persisted assessment, it explains
    the verdict from recorded fields only and never invents evidence.
    """
    text = claim.get("text", "")
    status = claim.get("status", "not_yet_analyzed")
    conf = claim.get("confidence", 0)
    sources = claim.get("evidence", []) or []
    excerpts = claim.get("excerpts", []) or []
    contradictions = (claim.get("contradictions", "") or "").strip()
    explanation = (claim.get("explanation", "") or "").strip()
    parts = [f'WHAT THE VIDEO SAYS: "{text}"']
    n = len(sources)
    status_line = _STATUS_LINE.get(status, "it could not be assessed")
    parts.append(f"EVIDENCE FOUND: {n} source(s) retrieved. "
                 + status_line[0].upper() + status_line[1:] + ".")
    if status == "contradicted":
        parts.append("REALITY CHECK: the claim does not hold up. "
                     + (contradictions or explanation))
    elif status == "supported":
        parts.append("REALITY CHECK: the claim holds up against the cited "
                     "sources. " + explanation)
    elif status == "mixed_evidence":
        parts.append("REALITY CHECK: partly confirmed, partly not. "
                     + (contradictions + " " if contradictions else "")
                     + explanation)
    elif status == "unverifiable":
        parts.append("REALITY CHECK: no true/false verdict applies. "
                     + explanation)
    else:
        parts.append("REALITY CHECK: no verdict is possible from the "
                     "retrieved evidence. " + explanation)
    if excerpts:
        parts.append("STRONGEST EXCERPT: \"" + excerpts[0][:300] + "\"")
    if sources:
        shown = "; ".join(s for s in sources[:3])
        parts.append(f"KEY SOURCES: {shown}")
    parts.append(f"WHY THIS VERDICT (confidence {conf}): {explanation} "
                 "A different verdict would need new evidence that "
                 "contradicts these sources.")
    return "\n".join(parts)


def build_payload(job_id: str, title: str, dimensions: dict, claims: list[dict],
                  sources: list[dict], errors: list[dict],
                  limitations: list[str], offline: bool,
                  metadata: dict | None = None) -> dict:
    return {"job_id": job_id, "title": title,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "dimensions": dimensions, "claims": claims, "sources": sources,
            "errors": errors, "limitations": limitations, "offline": offline,
            "metadata": metadata or {}}


def to_markdown(p: dict) -> str:
    L = [f"# {p.get('title','Analysis')} ", f"Job: `{p['job_id']}`, {p['created_at']}",
         " (SYNTHETIC DEMO, not real analysis, no live verification)" if p.get("offline") else ""]
    for dim in DIMENSIONS:
        d = p["dimensions"].get(dim, {})
        L.append(f"\n## {dim.replace('_',' ').title()}\n")
        L.append(d if isinstance(d, str) else json.dumps(d, indent=2, default=str))
    metadata = p.get("metadata") or {}
    if metadata:  # operational metadata: explicitly not a sixth dimension
        L.append("\n## Operational Metadata\n")
        L.append(json.dumps(metadata, indent=2, default=str))
    L.append("\n## Claims\n")
    for c in p["claims"]:
        L.append(f"### [{c.get('status','?')}] {c.get('text','')}\n")
        L.append(verdict_story(c) + "\n")
    L.append("\n## Sources\n")
    for s in p["sources"]:
        L.append(f"- [{s.get('title') or s.get('url')}]({s.get('url')}), {s.get('publisher','')}")
    if p.get("limitations"):
        L.append("\n## Limitations\n" + "\n".join(f"- {x}" for x in p["limitations"]))
    return "\n".join(L)


def export(payload: dict, out_dir: str | Path, fmt: str = "json") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if fmt == "markdown":
        path = out / f"{payload['job_id']}.md"
        path.write_text(to_markdown(payload))
    else:
        path = out / f"{payload['job_id']}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
    return path
