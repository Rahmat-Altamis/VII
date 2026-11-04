"""Thin service facade used by both the Qt UI and the FastAPI routes."""
from __future__ import annotations

from vii.application.pipeline import Pipeline
from vii.config import Settings
from vii.domain.schemas import AnalysisCreate
from vii.persistence.db import init_db
from vii.persistence.models import AnalysisJob
from vii.persistence.repositories import AnalysisRepo, JobRepo


class AnalysisService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or __import__("vii.config", fromlist=["get_settings"]).get_settings()
        self.Session = init_db(self.settings.database_url, self.settings.storage_dir)
        self.pipeline = Pipeline(self.settings, self.Session)

    def create(self, req: AnalysisCreate, consumer: str = "default") -> str:
        return self.pipeline.create_job(req, consumer)

    def run(self, job_id: str, progress=None) -> dict:
        return self.pipeline.run(job_id, progress)

    def get(self, job_id: str, consumer: str | None = None) -> dict | None:
        with self.Session() as db:
            job = JobRepo(db).get(job_id)
            if not job:
                return None
            if consumer and str(job.consumer) != consumer:
                return None  # consumer isolation: no cross-consumer reads
            return self._detail(db, job)

    def list(self, limit: int = 100, consumer: str | None = None) -> list[dict]:
        with self.Session() as db:
            repo = JobRepo(db)
            jobs = repo.list_for_consumer(consumer, limit) if consumer else repo.list(limit)
            return [{"id": j.id, "title": j.title, "status": j.status,
                     "source_kind": j.source_kind, "offline": bool(j.offline),
                     "created_at": j.created_at.isoformat()} for j in jobs]

    def _detail(self, db, job: AnalysisJob) -> dict:
        repo = AnalysisRepo(db)
        claims = []
        for c in repo.claims_for_job(job.id):
            a = c.assessment
            import json as _json
            claims.append({"id": c.id, "text": c.text, "kind": c.kind,
                           "start_s": c.start_s, "end_s": c.end_s,
                           "assessment": None if not a else {
                               "status": a.status, "explanation": a.explanation,
                               "evidence": _json.loads(a.evidence_json or "[]"),
                               "excerpts": _json.loads(a.excerpts_json or "[]"),
                               "contradictions": a.contradictions,
                               "confidence": a.confidence, "limitations": a.limitations,
                               "method": a.method}})
        return {
            "id": job.id, "title": job.title, "status": job.status,
            "source_kind": job.source_kind, "source_ref": job.source_ref,
            "acquisition_method": job.acquisition_method, "offline": bool(job.offline),
            "claims": claims,
            "evidence": [{"url": e.url, "title": e.title, "snippet": e.snippet,
                          "publisher": e.publisher, "method": e.method,
                          "relationship": e.relationship or "",
                          "publication_date": e.publication_date or "",
                          "retrieved_at": (e.retrieved_at.isoformat()
                                           if e.retrieved_at else ""),
                          "claim_id": e.claim_id} for e in repo.evidence_for_job(job.id)],
            "citations": [{"url": c.url, "span": c.cited_span, "claim_id": c.claim_id}
                          for c in repo.citations_for_job(job.id)],
            "transcript": [{"start_s": s.start_s, "end_s": s.end_s, "text": s.text,
                            "speaker": s.speaker, "engine": s.engine}
                           for s in repo.segments_for_job(job.id)],
            "log": [{"stage": entry.stage, "level": entry.level, "message": entry.message,
                     "at": entry.created_at.isoformat()} for entry in JobRepo(db).logs(job.id)],
        }

    def diagnostics(self) -> dict:
        import shutil
        s = self.settings
        from vii.providers.capabilities import provider_capabilities
        return {"settings": s.redacted(), "live_mode": s.live_mode,
                "ffmpeg": shutil.which(s.ffmpeg_bin) is not None,
                "ffprobe": shutil.which(s.ffprobe_bin) is not None,
                "capabilities": provider_capabilities(s)}
