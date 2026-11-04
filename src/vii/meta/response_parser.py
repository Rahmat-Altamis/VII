"""Parse Responses API outputs: text, web_search_call(+results), url_citation."""
from __future__ import annotations

from typing import Any

from vii.domain.schemas import CitationAnnotation, SearchResultItem, VideoUnderstanding


def _content_list(resp: dict) -> list[dict]:
    out = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if isinstance(c, dict):
                out.append(c)
    return out


def output_text(resp: dict) -> str:
    return "\n".join(c.get("text", "") for c in _content_list(resp)
                     if c.get("type") in ("output_text", "text")).strip()


def output_annotations(resp: dict) -> list[dict]:
    anns = []
    for c in _content_list(resp):
        anns.extend(c.get("annotations", []) or [])
    return anns


def parse_search_results(resp: dict, method: str = "meta_web_search") -> list[SearchResultItem]:
    """Extract web_search_call.results records + response id."""
    items: list[SearchResultItem] = []
    rid = resp.get("id", "")
    for item in resp.get("output", []) or []:
        if item.get("type") != "web_search_call":
            continue
        rid = item.get("id", rid) or rid
        for r in (item.get("results") or item.get("action", {}).get("results") or []):
            if not isinstance(r, dict) or not r.get("url"):
                continue
            items.append(SearchResultItem(
                url=r["url"], title=r.get("title", ""), snippet=r.get("snippet", r.get("text", "")),
                publisher=r.get("publisher", r.get("source", "")),
                relationship=str(r.get("relationship") or r.get("relation")
                                 or r.get("stance") or ""),
                publication_date=str(r.get("publication_date")
                                     or r.get("published_at")
                                     or r.get("published_date")
                                     or r.get("date") or ""),
                search_response_id=str(item.get("id", rid)), method=method))  # type: ignore[arg-type]
    return items


def parse_citations(resp: dict, claim_ids: list[str] | None = None) -> list[CitationAnnotation]:
    out: list[CitationAnnotation] = []
    rid = resp.get("id", "")
    for a in output_annotations(resp):
        if a.get("type") != "url_citation" or not a.get("url"):
            continue
        out.append(CitationAnnotation(
            url=a["url"], title=a.get("title", ""), cited_span=a.get("cited_text", a.get("text", "")),
            start_index=int(a.get("start_index", 0) or 0), end_index=int(a.get("end_index", 0) or 0),
            claim_ids=list(claim_ids or []), search_response_id=rid))
    return out


def search_performed(resp: dict) -> bool:
    return any(i.get("type") == "web_search_call" for i in resp.get("output", []) or [])


def parse_video_json(text: str, raw: str = "", offline: bool = False) -> VideoUnderstanding:
    """Validate model JSON; fall back to summary-only on malformed output."""
    import json as _json
    try:
        start, end = text.find("{"), text.rfind("}")
        data = _json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    claims = [c for c in data.get("factual_claims", []) if isinstance(c, dict) and c.get("text")]
    vu = VideoUnderstanding(
        summary=str(data.get("summary", text[:2000])),
        events=[str(e) for e in data.get("events", [])][:50],
        visual_observations=[str(o) for o in data.get("visual_observations", [])][:50],
        on_screen_text=[str(t) for t in data.get("on_screen_text", [])][:50],
        ambiguities=[str(a) for a in data.get("ambiguous_statements", data.get("ambiguities", []))][:30],
        open_questions=[str(q) for q in data.get("open_questions", [])][:30],
        raw_response=raw or text[:20000], offline=offline)
    ents = data.get("entities", {})
    if isinstance(ents, dict):
        vu.entities = {k: [str(x) for x in v][:20] for k, v in ents.items() if isinstance(v, list)}
    vu.__dict__["_claims"] = claims
    return vu


def parsed_claims(vu: VideoUnderstanding) -> list[dict[str, Any]]:
    return vu.__dict__.get("_claims", [])
