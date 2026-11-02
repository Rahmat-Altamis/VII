"""JSON + Markdown report export. Five dimensions kept separate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS = ["claim_verification", "supporting_contradicting_evidence",
              "media_origin", "originality", "uncertainty_limitations"]


def build_payload(job_id: str, title: str, dimensions: dict, claims: list[dict],
                  sources: list[dict], errors: list[dict],
                  limitations: list[str], offline: bool) -> dict:
    return {"job_id": job_id, "title": title,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "dimensions": dimensions, "claims": claims, "sources": sources,
            "errors": errors, "limitations": limitations, "offline": offline}


def to_markdown(p: dict) -> str:
    L = [f"# {p.get('title','Analysis')} ", f"Job: `{p['job_id']}` — {p['created_at']}",
         " (SYNTHETIC DEMO — not real analysis, no live verification)" if p.get("offline") else ""]
    for dim in DIMENSIONS:
        d = p["dimensions"].get(dim, {})
        L.append(f"\n## {dim.replace('_',' ').title()}\n")
        L.append(d if isinstance(d, str) else json.dumps(d, indent=2, default=str))
    L.append("\n## Claims\n")
    for c in p["claims"]:
        L.append(f"- **{c.get('status','?')}** · {c.get('text','')} "
                 f"({len(c.get('evidence',[]))} sources)")
    L.append("\n## Sources\n")
    for s in p["sources"]:
        L.append(f"- [{s.get('title') or s.get('url')}]({s.get('url')}) — {s.get('publisher','')}")
    if p.get("limitations"):
        L.append("\n## Limitations\n" + "\n".join(f"- {x}" for x in p["limitations"]))
    return "\n".join(L)


def export(payload: dict, out_dir: str | Path, fmt: str = "json") -> Path:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    if fmt == "markdown":
        path = out / f"{payload['job_id']}.md"
        path.write_text(to_markdown(payload))
    else:
        path = out / f"{payload['job_id']}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
    return path
