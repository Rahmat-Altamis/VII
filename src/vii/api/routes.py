"""REST routes: analyses, jobs, reports, health, diagnostics.

DEPRECATED legacy surface (unversioned). Preserved for local development
compatibility only; new consumers must use /v1 (vii.api.v1). Handlers now
apply the same consumer authentication/isolation as v1 (previously they
ignored VII_REQUIRE_AUTH entirely, exposing every consumer's jobs when
auth was enabled). /health stays unauthenticated for liveness probes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from vii.api.v1 import consumer_id
from vii.application.services import AnalysisService
from vii.config import get_settings
from vii.domain.schemas import AnalysisCreate
from vii.errors import ProviderConfigurationError, ProviderError

router = APIRouter()
_service: AnalysisService | None = None
_lock = __import__("threading").Lock()


def svc() -> AnalysisService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = AnalysisService(get_settings())
    return _service


@router.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "live_mode": s.live_mode, "offline_mode": s.offline_mode,
            "model": s.meta_model}


@router.get("/diagnostics")
def diagnostics(auth: str = Depends(consumer_id)):
    return svc().diagnostics()


@router.post("/analyses", status_code=201)
def create_analysis(req: AnalysisCreate, auth: str = Depends(consumer_id)):
    try:
        job_id = svc().create(req, auth)
    except ProviderConfigurationError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"job_id": job_id}


@router.post("/analyses/{job_id}/run")
def run_analysis(job_id: str, auth: str = Depends(consumer_id)):
    if not svc().get(job_id, auth):
        raise HTTPException(404, "unknown job")
    try:
        return svc().run(job_id)
    except ProviderConfigurationError as e:
        raise HTTPException(503, str(e)) from e
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.get("/analyses")
def list_analyses(limit: int = 100, auth: str = Depends(consumer_id)):
    return svc().list(limit, auth)


@router.get("/analyses/{job_id}")
def get_analysis(job_id: str, auth: str = Depends(consumer_id)):
    d = svc().get(job_id, auth)
    if not d:
        raise HTTPException(404, "unknown job")
    return d


@router.get("/analyses/{job_id}/report", response_class=PlainTextResponse)
def get_report(job_id: str, format: str = "markdown",
               auth: str = Depends(consumer_id)):
    from pathlib import Path
    d = svc().get(job_id, auth)
    if not d:
        raise HTTPException(404, "unknown job")
    s = get_settings()
    ext = "md" if format == "markdown" else "json"
    path = Path(s.storage_dir) / "exports" / f"{job_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "report not generated yet, run the analysis first")
    return path.read_text()
