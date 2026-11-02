"""Claim-grouped retrieval orchestration over Meta web search.

Without a live client no search is performed: results are empty and
``performed`` is False. That state is explicit (demo mode or unavailable),
never fabricated evidence."""
from __future__ import annotations

from typing import TYPE_CHECKING

from vii.domain.enums import SearchMethod
from vii.domain.schemas import CitationAnnotation, SearchResultItem
from vii.meta import response_parser as rp
from vii.meta.search import build_search_payload, offline_note

if TYPE_CHECKING:
    from vii.config import Settings
    from vii.meta.client import MetaClient


def no_search_stub(query: str) -> tuple[list[SearchResultItem], str]:
    """Explicit no-search result — never presented as live evidence."""
    return [], f"NO SEARCH PERFORMED (no live provider client) for: {query[:120]}"


def search_claim(query: str, claim_id: str, settings: "Settings",
                 client: "MetaClient | None" = None) -> dict:
    """Returns {results, citations, response_id, performed, offline, note}."""
    if client is None or not client.live:
        _, note = no_search_stub(query)
        return {"results": [], "citations": [], "response_id": "",
                "performed": False, "offline": True,
                "note": note or offline_note(settings)}
    payload = build_search_payload(query, settings.meta_model, settings.search_context_size)
    resp = client.responses_create(payload)
    performed = rp.search_performed(resp)
    rid = resp.get("id", "")
    results = rp.parse_search_results(resp, SearchMethod.META_WEB_SEARCH)
    citations = rp.parse_citations(resp, [claim_id])
    return {"results": results, "citations": citations, "response_id": rid,
            "performed": performed, "offline": False, "note": ""}


def claim_query(claim_text: str) -> str:
    return f"Verify with primary or high-quality sources: {claim_text.strip()[:400]}"
