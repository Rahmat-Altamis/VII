"""Meta provider adapter (Muse Spark) — compatibility layer over vii.meta.

The single Meta transport in this codebase is vii.meta.client.MetaClient
(Responses API at META_BASE_URL, default https://api.meta.ai/v1). The previous
revision of this file targeted ``api.llama.com/compat/v1`` chat-completions;
that path is removed — it is not the documented Muse Spark endpoint and it
duplicated the client. This module keeps the legacy Provider interface
(describe/extract/search/verify) so older call sites keep working, delegating
every call to the active Responses API implementation.

LIVE-INTEGRATION STATUS: not verified in this environment (no credentials).
Mock-based tests cover the pipeline; live calls need MODEL_API_KEY.
"""
from __future__ import annotations

import httpx

from vii.logging_setup import log
from vii.meta import response_parser as rp
from vii.meta.client import MetaClient
from vii.meta.search import build_search_payload
from vii.meta.video import build_file_id_payload, build_url_payload

from .base import (
    ClaimVerdict,
    ExtractedClaim,
    RetrievedSource,
    UnderstandingResult,
    parse_json_block,
)


class MetaError(RuntimeError):
    pass


class MetaProvider:
    name = "meta"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.meta.ai/v1",
        model: str = "muse-spark-1.3",
        timeout_s: float = 120.0,
        max_retries: int = 2,
        transcription_model: str = "muse-voice-transcribe-1.0",
    ) -> None:
        if not api_key:
            raise MetaError("Meta API key is missing. Set MODEL_API_KEY or enter it in Settings.")
        self.client = MetaClient(api_key, base_url.rstrip("/"), model,
                                 timeout_s, max_retries, transcription_model)

    @property
    def api_key(self) -> str:
        return self.client.api_key

    @property
    def base_url(self) -> str:
        return self.client.base_url

    @property
    def model(self) -> str:
        return self.client.model

    # -- transport ------------------------------------------------------
    def ping(self) -> tuple[bool, str]:
        """Lightweight connection test against <base>/models. Returns (ok, message)."""
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{self.base_url}/models",
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            ok = resp.status_code < 400
            return (ok, f"HTTP {resp.status_code}" + ("" if ok else f": {resp.text[:200]}"))
        except Exception as exc:  # noqa: BLE001
            return (False, f"connection failed: {exc}"[:300])

    # -- pipeline steps (legacy interface, active implementation) -----------
    def describe_video(self, context: dict) -> UnderstandingResult:
        """Native video understanding. Requires context['video_url'] or context['file_id']."""
        video_url = context.get("video_url")
        file_id = context.get("file_id")
        instructions = context.get("instructions")
        if not video_url and not file_id:
            raise MetaError("describe_video needs context['video_url'] or context['file_id'] "
                            "(native video input — frame stills are not used here).")
        payload = (build_url_payload(video_url, self.model, instructions) if video_url
                   else build_file_id_payload(file_id, self.model, instructions))
        try:
            resp = self.client.responses_create(payload)
        except RuntimeError as exc:
            raise MetaError(str(exc)) from exc
        text = rp.output_text(resp)
        vu = rp.parse_video_json(text, raw=text, offline=False)
        return UnderstandingResult(
            subject=vu.summary,
            events=vu.events,
            narration="",
            on_screen_text="\n".join(vu.on_screen_text),
            ambiguities=[*vu.ambiguities, *vu.open_questions],
            method=f"meta {self.model}: native video understanding (input_video/file_id)",
        )

    def extract_claims(self, understanding: UnderstandingResult) -> list[ExtractedClaim]:
        prompt = (
            "Extract atomic, verifiable factual claims from this video description. "
            "Separate opinions, predictions, satire and subjective statements "
            "(label those category='non_factual') from checkable claims.\n\n"
            f"Subject: {understanding.subject}\nEvents: {understanding.events}\n"
            f"On-screen text: {understanding.on_screen_text}\n\n"
            "Return ONLY a JSON array of objects with keys: "
            "text, category, t_start, t_end, why_verifiable, uncertainty."
        )
        try:
            resp = self.client.responses_create(
                {"model": self.model,
                 "input": [{"role": "user",
                            "content": [{"type": "input_text", "text": prompt}]}]})
        except RuntimeError as exc:
            raise MetaError(str(exc)) from exc
        try:
            data = parse_json_block(rp.output_text(resp))
        except Exception as exc:  # noqa: BLE001
            raise MetaError(f"Could not parse claim extraction as JSON: {exc}") from exc
        if not isinstance(data, list):
            raise MetaError("Claim extraction did not return a JSON array.")
        claims: list[ExtractedClaim] = []
        for item in data:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            try:
                t_start = float(item.get("t_start", 0.0) or 0.0)
                t_end = float(item.get("t_end", 0.0) or 0.0)
            except (TypeError, ValueError):
                t_start, t_end = 0.0, 0.0
            claims.append(ExtractedClaim(
                text=str(item["text"]).strip()[:2000],
                category=str(item.get("category", "factual")),
                t_start=t_start, t_end=t_end,
                why_verifiable=str(item.get("why_verifiable", "")),
                uncertainty=str(item.get("uncertainty", ""))))
        return claims

    def search_evidence(self, claim_text: str) -> list[RetrievedSource]:
        """Real Meta web_search retrieval. Returns [] when no search was performed."""
        try:
            resp = self.client.responses_create(
                build_search_payload(claim_text, self.model))
        except RuntimeError as exc:
            raise MetaError(str(exc)) from exc
        if not rp.search_performed(resp):
            log.warning("web_search tool was not invoked by the model; returning no sources")
            return []
        rid = resp.get("id", "")
        cited_urls = {c.url for c in rp.parse_citations(resp)}
        out: list[RetrievedSource] = []
        for r in rp.parse_search_results(resp):
            flag = "cited by model" if r.url in cited_urls else "retrieved, not model-cited"
            out.append(RetrievedSource(
                title=r.title, publisher=r.publisher or "", url=r.url,
                published_at="", excerpt=r.snippet, relation="context",
                credibility_note=f"Retrieved via Meta web_search (response {r.search_response_id or rid}); {flag}.",
                retrieval_method="meta_web_search"))
        return out

    def verify_claim(self, claim_text: str, sources: list[RetrievedSource]) -> ClaimVerdict:
        if not sources:
            return ClaimVerdict(
                status="insufficient",
                reasoning="No evidence was retrieved, so the claim cannot be assessed.",
                evidence_indexes=[],
                method=f"meta {self.model}: no-evidence rule")
        ev_lines = "\n".join(
            f"[{i}] {s.title} ({s.publisher}) — {s.excerpt[:400]} [{s.url}]"
            for i, s in enumerate(sources))
        prompt = (
            "You verify a claim ONLY against the numbered sources below. Cite source numbers. "
            "If sources are thin or conflicted, say so. Never use knowledge beyond the sources.\n\n"
            f"Claim: {claim_text}\nSources:\n{ev_lines}\n\n"
            "Return ONLY a JSON object with keys: "
            "status (supported|contradicted|mixed|insufficient|unverifiable), "
            "reasoning, evidence_indexes (list of 0-based ints).")
        try:
            resp = self.client.responses_create(
                {"model": self.model,
                 "input": [{"role": "user",
                            "content": [{"type": "input_text", "text": prompt}]}]})
        except RuntimeError as exc:
            raise MetaError(str(exc)) from exc
        try:
            data = parse_json_block(rp.output_text(resp))
        except Exception as exc:  # noqa: BLE001
            raise MetaError(f"Verification did not return JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MetaError("Verification did not return a JSON object.")
        status = str(data.get("status", "insufficient"))
        if status not in ("supported", "contradicted", "mixed", "insufficient", "unverifiable"):
            status = "insufficient"
        idx = [int(i) for i in (data.get("evidence_indexes", []) or [])
               if isinstance(i, int) and 0 <= i < len(sources)]
        if status in ("supported", "contradicted") and not idx:
            status = "insufficient"  # enforce: no mapped citation -> cannot assert
        return ClaimVerdict(status=status, reasoning=str(data.get("reasoning", "")),
                            evidence_indexes=idx,
                            method=f"meta {self.model}: evidence-grounded verification")
