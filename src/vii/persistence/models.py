"""SQLAlchemy ORM models (SQLite default, PostgreSQL-compatible)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(64), default="queued")
    consumer: Mapped[str] = mapped_column(String(128), default="default")
    source_kind: Mapped[str] = mapped_column(String(32), default="")
    source_ref: Mapped[str] = mapped_column(Text, default="")  # url or local path
    acquisition_method: Mapped[str] = mapped_column(String(64), default="")
    offline: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    sources: Mapped[list[VideoSource]] = relationship(back_populates="job", cascade="all, delete-orphan")
    claims: Mapped[list[Claim]] = relationship(back_populates="job", cascade="all, delete-orphan")


class VideoSource(Base):
    __tablename__ = "video_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("analysis_jobs.id"))
    kind: Mapped[str] = mapped_column(String(32), default="")
    ref: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(128), default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    job: Mapped[AnalysisJob] = relationship(back_populates="sources")


class MetaRequest(Base):
    __tablename__ = "meta_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    purpose: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    response_id: Mapped[str] = mapped_column(String(128), default="")
    offline: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("analysis_jobs.id"))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="factual")
    start_s: Mapped[float] = mapped_column(Float, nullable=True)
    end_s: Mapped[float] = mapped_column(Float, nullable=True)
    job: Mapped[AnalysisJob] = relationship(back_populates="claims")
    assessment: Mapped[ClaimAssessment | None] = relationship(back_populates="claim", cascade="all, delete-orphan", uselist=False)


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    claim_id: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    publisher: Mapped[str] = mapped_column(String(256), default="")
    method: Mapped[str] = mapped_column(String(64), default="")
    relationship: Mapped[str] = mapped_column(String(32), default="")
    publication_date: Mapped[str] = mapped_column(String(64), default="")
    search_response_id: Mapped[str] = mapped_column(String(128), default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Citation(Base):
    __tablename__ = "citations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    claim_id: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(Text)
    cited_span: Mapped[str] = mapped_column(Text, default="")
    start_index: Mapped[int] = mapped_column(Integer, default=0)
    end_index: Mapped[int] = mapped_column(Integer, default=0)
    search_response_id: Mapped[str] = mapped_column(String(128), default="")


class ClaimAssessment(Base):
    __tablename__ = "claim_assessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"))
    status: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    excerpts_json: Mapped[str] = mapped_column(Text, default="[]")
    contradictions: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    limitations: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(128), default="")
    claim: Mapped[Claim] = relationship(back_populates="assessment")


class TranscriptSegmentRow(Base):
    __tablename__ = "transcript_segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    text: Mapped[str] = mapped_column(Text, default="")
    speaker: Mapped[str] = mapped_column(String(128), default="")
    engine: Mapped[str] = mapped_column(String(128), default="")


class SearchSession(Base):
    __tablename__ = "search_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    claim_id: Mapped[str] = mapped_column(String(64), default="")
    query: Mapped[str] = mapped_column(Text, default="")
    response_id: Mapped[str] = mapped_column(String(128), default="")
    offline: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProcessingLog(Base):
    __tablename__ = "processing_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    stage: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReportRow(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), default="")
    format: Mapped[str] = mapped_column(String(16), default="json")
    path: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DatasetSample(Base):
    """Unclassified Dataset Inbox: videos registered before any annotation.

    Every import starts with annotation_status='pending' (valid state).
    AI-proposed labels stay provisional until human review.
    """
    __tablename__ = "dataset_samples"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(128), default="default")
    video_id: Mapped[str] = mapped_column(String(128), default="")  # stable external id
    source_url: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(64), default="")
    storage_ref: Mapped[str] = mapped_column(Text, default="")  # local path or s3:// URI
    sha256: Mapped[str] = mapped_column(String(128), default="")
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint_json: Mapped[str] = mapped_column(Text, default="{}")
    annotation_status: Mapped[str] = mapped_column(String(32), default="pending")
    labels_json: Mapped[str] = mapped_column(Text, default="[]")  # provisional, human-review needed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
