"""Repository pattern, all DB access goes through here."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from vii.domain.enums import JobStatus
from vii.persistence.models import (
    AnalysisJob,
    Citation,
    Claim,
    ClaimAssessment,
    DatasetSample,
    EvidenceSource,
    MetaRequest,
    ProcessingLog,
    ReportRow,
    SearchSession,
    TranscriptSegmentRow,
    VideoSource,
)


def new_id(prefix: str = "job") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class JobRepo:
    def __init__(self, s: Session):
        self.s = s
    def create(self, title: str, source_kind: str, source_ref: str, offline: bool,
               consumer: str = "default") -> AnalysisJob:
        j = AnalysisJob(id=new_id(), title=title, status=JobStatus.QUEUED,
                        consumer=consumer or "default",
                        source_kind=source_kind, source_ref=source_ref, offline=int(offline))
        self.s.add(j)
        self.s.commit()
        return j
    def get(self, job_id: str) -> AnalysisJob | None:
        return self.s.get(AnalysisJob, job_id)
    def list(self, limit: int = 100) -> list[AnalysisJob]:
        return (self.s.query(AnalysisJob).order_by(AnalysisJob.created_at.desc()).limit(limit).all())
    def list_for_consumer(self, consumer: str, limit: int = 100) -> list[AnalysisJob]:
        return (self.s.query(AnalysisJob).filter_by(consumer=consumer or "default")
                .order_by(AnalysisJob.created_at.desc()).limit(limit).all())
    def set_status(self, job: AnalysisJob, status: JobStatus, method: str = ""):
        job.status = str(status)
        job.updated_at = datetime.now(UTC)
        if method:
            job.acquisition_method = method
        self.s.commit()
    def log(self, job_id: str, stage: str, message: str, level: str = "info"):
        self.s.add(ProcessingLog(job_id=job_id, stage=stage, level=level, message=message))
        self.s.commit()
    def logs(self, job_id: str) -> list[ProcessingLog]:
        return self.s.query(ProcessingLog).filter_by(job_id=job_id).order_by(ProcessingLog.id).all()


class AnalysisRepo:
    """Claims, evidence, citations, assessments, transcripts, meta requests, reports."""
    def __init__(self, s: Session):
        self.s = s
    def add_source(self, job_id: str, kind: str, ref: str, sha256: str = "", meta: dict | None = None):
        self.s.add(VideoSource(job_id=job_id, kind=kind, ref=ref, sha256=sha256,
                               meta_json=json.dumps(meta or {})))
        self.s.commit()
    def add_claim(self, job_id: str, claim_id: str, text: str, kind: str,
                  start_s: float | None, end_s: float | None):
        self.s.add(Claim(id=claim_id, job_id=job_id, text=text, kind=kind,
                         start_s=start_s, end_s=end_s))
        self.s.commit()
    def add_evidence(self, job_id: str, claim_id: str, url: str, title: str, snippet: str,
                     publisher: str, method: str, response_id: str,
                     relationship: str = "", publication_date: str = "") -> bool:
        """Persist one evidence source; skip exact duplicates (resume-safe).

        Returns True when a new row was stored, False when an identical
        (job, claim, url) record already existed.
        """
        exists = (self.s.query(EvidenceSource)
                  .filter_by(job_id=job_id, claim_id=claim_id, url=url).first())
        if exists is not None:
            return False
        self.s.add(EvidenceSource(job_id=job_id, claim_id=claim_id, url=url, title=title,
                                  snippet=snippet, publisher=publisher, method=method,
                                  relationship=relationship or "",
                                  publication_date=publication_date or "",
                                  search_response_id=response_id or ""))
        self.s.commit()
        return True
    def add_citation(self, job_id: str, claim_id: str, url: str, span: str,
                     start: int, end: int, response_id: str):
        self.s.add(Citation(job_id=job_id, claim_id=claim_id, url=url, cited_span=span,
                            start_index=start, end_index=end,
                            search_response_id=response_id))
        self.s.commit()
    def add_assessment(self, claim_id: str, status: str, explanation: str,
                       evidence: list[str], excerpts: list[str], contradictions: str,
                       confidence: float, limitations: str, method: str):
        self.s.add(ClaimAssessment(claim_id=claim_id, status=status, explanation=explanation,
                                   evidence_json=json.dumps(evidence),
                                   excerpts_json=json.dumps(excerpts),
                                   contradictions=contradictions, confidence=confidence,
                                   limitations=limitations, method=method))
        self.s.commit()
    def add_transcript_segment(self, job_id: str, start_s: float, end_s: float,
                               text: str, speaker: str, engine: str):
        self.s.add(TranscriptSegmentRow(job_id=job_id, start_s=start_s, end_s=end_s,
                                        text=text, speaker=speaker or "", engine=engine))
        self.s.commit()
    def add_meta_request(self, job_id: str, purpose: str, model: str,
                         request: dict, response_id: str, offline: bool):
        self.s.add(MetaRequest(job_id=job_id, purpose=purpose, model=model,
                               request_json=json.dumps(request, default=str)[:20000],
                               response_id=response_id, offline=int(offline)))
        self.s.commit()
    def add_search_session(self, sid: str, job_id: str, claim_id: str, query: str,
                           response_id: str, offline: bool):
        self.s.add(SearchSession(id=sid, job_id=job_id, claim_id=claim_id, query=query,
                                 response_id=response_id, offline=int(offline)))
        self.s.commit()
    def add_report(self, job_id: str, fmt: str, path: str, payload: dict):
        self.s.add(ReportRow(job_id=job_id, format=fmt, path=path,
                             payload_json=json.dumps(payload, default=str)))
        self.s.commit()
    def report_payload(self, job_id: str, fmt: str = "json") -> dict | None:
        """Latest persisted report payload for a job (None when not yet generated)."""
        row = (self.s.query(ReportRow).filter_by(job_id=job_id, format=fmt)
               .order_by(ReportRow.id.desc()).first())
        if row is None:
            return None
        try:
            return json.loads(row.payload_json or "{}")
        except Exception:
            return None
    def clear_job_artifacts(self, job_id: str) -> None:
        """Remove partial per-job outputs so a job can be re-run safely.

        A run that failed midway (worker retry, manual re-run) must not
        collide with its own earlier claims (job-scoped primary keys),
        evidence, transcripts, or reports. Processing logs and the job
        row itself are preserved for audit.
        """
        claim_ids = [c.id for c in
                     self.s.query(Claim).filter_by(job_id=job_id).all()]
        if claim_ids:
            (self.s.query(ClaimAssessment)
             .filter(ClaimAssessment.claim_id.in_(claim_ids)).delete(
                 synchronize_session=False))
        for model in (VideoSource, MetaRequest, Claim, EvidenceSource,
                      Citation, TranscriptSegmentRow, SearchSession, ReportRow):
            (self.s.query(model).filter_by(job_id=job_id)
             .delete(synchronize_session=False))
        self.s.commit()

    def claims_for_job(self, job_id: str) -> list[Claim]:
        return self.s.query(Claim).filter_by(job_id=job_id).all()
    def evidence_for_job(self, job_id: str) -> list[EvidenceSource]:
        return self.s.query(EvidenceSource).filter_by(job_id=job_id).all()
    def citations_for_job(self, job_id: str) -> list[Citation]:
        return self.s.query(Citation).filter_by(job_id=job_id).all()
    def segments_for_job(self, job_id: str) -> list[TranscriptSegmentRow]:
        return self.s.query(TranscriptSegmentRow).filter_by(job_id=job_id).order_by(TranscriptSegmentRow.start_s).all()


class DatasetRepo:
    """Unclassified inbox + fingerprint persistence + incremental search."""

    def __init__(self, s: Session):
        self.s = s

    def register(self, consumer: str, video_id: str, source_url: str = "",
                 platform: str = "", storage_ref: str = "", sha256: str = "",
                 duration_s: float = 0.0, meta: dict | None = None) -> DatasetSample:
        row = DatasetSample(id=new_id("sample"), consumer=consumer or "default",
                            video_id=video_id, source_url=source_url,
                            platform=platform, storage_ref=storage_ref,
                            sha256=sha256, duration_s=duration_s,
                            meta_json=json.dumps(meta or {}),
                            annotation_status="pending")
        self.s.add(row)
        self.s.commit()
        return row

    def get(self, sample_id: str, consumer: str) -> DatasetSample | None:
        row = self.s.get(DatasetSample, sample_id)
        if row is None or str(row.consumer) != (consumer or "default"):
            return None
        return row

    def get_by_consumer_video(self, consumer: str, video_id: str) -> DatasetSample | None:
        """Idempotency lookup for CSV ingestion: one inbox row per
        (consumer, video_id). Returns None when the video is not yet
        registered for this consumer."""
        return (self.s.query(DatasetSample)
                .filter_by(consumer=consumer or "default", video_id=video_id)
                .first())

    def list_for_consumer(self, consumer: str, limit: int = 100,
                          status: str | None = None) -> list[DatasetSample]:
        q = self.s.query(DatasetSample).filter_by(consumer=consumer or "default")
        if status:
            q = q.filter_by(annotation_status=status)
        return q.order_by(DatasetSample.created_at.desc()).limit(limit).all()

    def set_fingerprint(self, sample_id: str, sha256: str, fp: dict) -> None:
        row = self.s.get(DatasetSample, sample_id)
        if row is None:
            return
        row.sha256 = sha256
        row.fingerprint_json = json.dumps(fp)
        self.s.commit()

    def set_labels(self, sample_id: str, labels: list, status: str = "pending") -> None:
        row = self.s.get(DatasetSample, sample_id)
        if row is None:
            return
        row.labels_json = json.dumps(labels)
        row.annotation_status = status
        self.s.commit()

    def search(self, consumer: str, query: str, limit: int = 20) -> list[DatasetSample]:
        """Substring search over video_id/source_url/platform + exact sha256 match."""
        q = (self.s.query(DatasetSample)
             .filter_by(consumer=consumer or "default"))
        like = f"%{query}%"
        rows = q.filter((DatasetSample.video_id.like(like)) |
                        (DatasetSample.source_url.like(like)) |
                        (DatasetSample.platform.like(like)) |
                        (DatasetSample.sha256 == query)).limit(limit).all()
        return rows
