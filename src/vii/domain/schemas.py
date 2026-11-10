"""Pydantic data contracts. No Qt / SQLAlchemy / HTTP imports allowed here."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from vii.domain.enums import (
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
    # Stance of this source toward the claim: supports | contradicts |
    # context | "" (provider did not state a stance). Assessment is
    # stance-based: SUPPORTED/CONTRADICTED require a matching stance.
    relationship: str = ""
    publication_date: str = ""
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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

    @model_validator(mode="after")
    def _needs_evidence(self) -> ClaimAssessmentIn:
        # Model-level (not field-level) validation: a field validator on
        # ``status`` runs before ``evidence_urls``/``explanation`` are
        # parsed in Pydantic v2, so it could never see them and made
        # SUPPORTED/CONTRADICTED impossible to construct at all.
        if self.status in (ClaimStatus.SUPPORTED, ClaimStatus.CONTRADICTED):
            if not self.evidence_urls:
                raise ValueError(
                    f"{self.status} requires at least one evidence URL")
            if not (self.explanation or "").strip():
                raise ValueError(f"{self.status} requires an explanation")
        return self


class MediaIngestionResult(BaseModel):
    """Result of ingestion-only validation (no job, no provider call).

    Produced by ``vii.media.ingestion.inspect_local_media``: the file was
    validated, signature-checked and hashed locally. ``duration_s`` is None
    when no local method could determine it, never guessed.
    """

    storage_ref: str
    sha256: str
    size_bytes: int
    size_mb: float
    extension: str
    container: str = "unknown"
    signature_ok: bool = False
    duration_s: float | None = None
    duration_source: str = "unknown"  # mp4_mvhd | ffprobe | unknown
    has_audio: bool | None = None
    native_video_ready: bool = False
    needs_conversion: bool = False
    limitations: list[str] = Field(default_factory=list)


class VisualObservation(BaseModel):
    """One provider-reported visual observation (not a factual finding).

    Optional fields stay None when the provider does not supply them;
    they are never filled by inference. Produced only by a real visual
    perception adapter, see vii.providers.visual.
    """

    observation_id: str = ""
    asset_id: str = ""
    provider: str = ""
    model: str = ""
    timestamp_ms: int | None = None
    frame_index: int | None = None
    observation_type: str = "detection"
    object_id: str | None = None
    label: str = ""
    description: str = ""
    geometry: dict[str, Any] | None = None
    mask_ref: str | None = None
    request_id: str = ""
    sampling_mode: str = "native_video"


class MediaOrigin(BaseModel):
    notes: str = ""
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    detector_used: str = "none, no AI-detector claimed"


class OriginalityResult(BaseModel):
    sha256: str = ""
    exact_duplicate_of: str | None = None
    phash_matches: list[dict[str, Any]] = Field(default_factory=list)
    phashes: list[str] = Field(default_factory=list)
    notes: str = ""


class ForensicSignal(BaseModel):
    """One evaluated manipulation-forensics signal (not a verdict)."""

    name: str
    status: str  # signal | no_signal | unavailable
    detail: str = ""
    value: float | None = None


class DeepfakeAssessment(BaseModel):
    """Manipulation-forensics result: categorical signals, never a
    fake/real verdict and never a fabricated probability.

    ``status`` is ``signals_detected`` when at least one signal fired,
    ``no_signals_detected`` when signals were evaluated and none fired,
    or ``unavailable`` when nothing could be evaluated locally. Individual
    signals are weak proxies (documented per signal); only a human
    reviewer with provenance records can conclude manipulation.
    """

    status: str = "unavailable"
    signals: list[ForensicSignal] = Field(default_factory=list)
    detector_used: str = (
        "local forensic signal ensemble (frame reuse, recompression "
        "error, temporal transitions, re-encode/screen layer, "
        "sensor-noise uniformity, light bias, spectral concentration, "
        "temporal flicker, audio room tone, provenance sparsity), no "
        "synthetic-media classifier was run")
    limitations: str = (
        "Signals are weak local proxies, not proof of manipulation or "
        "authenticity; platform re-encoding and ordinary editing fire "
        "several of them on genuine media. A detected re-encode/screen "
        "layer discounts pixel-level signals because it washes out "
        "sensor fingerprints. Temporal flicker and audio room tone are "
        "evaluated even under a re-encode layer; cuts, lighting "
        "changes, and studio audio fire them on genuine media.")


class JobProgress(BaseModel):
    job_id: str
    status: JobStatus
    stage: StageName | None = None
    message: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReportPayload(BaseModel):
    job_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dimensions: dict[str, Any] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    offline: bool = False
