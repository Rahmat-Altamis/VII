"""Pydantic data contracts. No Qt / SQLAlchemy / HTTP imports allowed here."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from vii.domain.enums import (
    AcquisitionMethod,
    ClaimKind,
    ClaimStatus,
    JobStatus,
    SearchMethod,
    SourceKind,
    StageName,
)


class VideoSourceIn(BaseModel):
    kind: SourceKind
    url: str | None = None
    local_path: str | None = None

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class AnalysisCreate(BaseModel):
    source: VideoSourceIn
    title: str | None = None
    # Explicit synthetic-demo opt-in. Online provider-backed analysis is the
    # default; demo is never selected implicitly (e.g. by a missing API key).
    demo: bool = False
    offline: bool = False  # deprecated alias of demo (explicit opt-in only)
    tasks: list[str] = Field(default_factory=list)  # subset of known tasks; [] = all

    @property
    def demo_requested(self) -> bool:
        return bool(self.demo or self.offline)


class InvestigateRequest(BaseModel):
    query: str
    claim_id: str | None = None
    context_size: str = "medium"


class CompareRequest(BaseModel):
    reference_sha256: str | None = None
    reference_job_id: str | None = None
    candidate_job_id: str | None = None
    candidate_sha256: str | None = None


class DatasetRegisterRequest(BaseModel):
    video_id: str
    source_url: str = ""
    platform: str = ""
    local_path: str | None = None  # server-side path; uploads use /v1/uploads instead
    storage_ref: str = ""


class ClaimIn(BaseModel):
    text: str
    kind: ClaimKind = ClaimKind.FACTUAL
    start_s: float | None = None
    end_s: float | None = None


class VideoUnderstanding(BaseModel):
    summary: str = ""
    events: list[str] = Field(default_factory=list)
    visual_observations: list[str] = Field(default_factory=list)
    on_screen_text: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    raw_response: str = ""
    offline: bool = False


class TranscriptSegment(BaseModel):
    start_s: float
    end_s: float
    text: str
    speaker: str | None = None


class Transcript(BaseModel):
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str | None = None
    engine: str = "unknown"
    offline: bool = False

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments)


class SearchResultItem(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    publisher: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    search_response_id: str = ""
    method: SearchMethod = SearchMethod.META_WEB_SEARCH


class CitationAnnotation(BaseModel):
    url: str
    title: str = ""
    cited_span: str = ""
    start_index: int = 0
    end_index: int = 0
    claim_ids: list[str] = Field(default_factory=list)
    search_response_id: str = ""


class ClaimAssessmentIn(BaseModel):
    claim_id: str
    status: ClaimStatus
    explanation: str
    evidence_urls: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)
    contradictions: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limitations: str = ""
    method: str = "meta_web_search"

    @field_validator("status")
    @classmethod
    def _needs_evidence(cls, v: ClaimStatus, info) -> ClaimStatus:
        data = info.data if hasattr(info, "data") else {}
        if v in (ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED):
            if not data.get("evidence_urls"):
                raise ValueError(f"{v} requires at least one evidence URL")
            if not (data.get("explanation") or "").strip():
                raise ValueError(f"{v} requires an explanation")
        return v


class MediaOrigin(BaseModel):
    notes: str = ""
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    detector_used: str = "none — no AI-detector claimed"


class OriginalityResult(BaseModel):
    sha256: str = ""
    exact_duplicate_of: str | None = None
    phash_matches: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class JobProgress(BaseModel):
    job_id: str
    status: JobStatus
    stage: StageName | None = None
    message: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReportPayload(BaseModel):
    job_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dimensions: dict[str, Any] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    offline: bool = False
