"""FastAPI application: versioned local HTTP API sharing services.

Legacy unversioned routes (vii.api.routes) are preserved. The v1 router
(vii.api.v1) is the consumer contract: analyses, async jobs, uploads,
investigate, compare, datasets, reports. A process-wide Worker starts with
the app lifespan so POST /v1/analyses actually executes in the background;
GET /v1/jobs/{id} polls its persisted status.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vii.api import routes
from vii.api.v1 import router as v1_router
from vii.api.v1 import worker as v1_worker
from vii.logging_setup import setup_logging

setup_logging()  # attach secret-redacting filter to all vii.* loggers


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    w = v1_worker()
    w.start()
    try:
        recovered = w.recover()
    except Exception:
        recovered = 0
    if recovered:
        logging.getLogger("vii.api").info("worker recovered %d stale job(s)", recovered)
    yield
    w.stop(wait=False)


app = FastAPI(title="Video Integrity Intelligence", version="1.0.0",
              description="Evidence-first video intelligence (Meta-native).",
              lifespan=lifespan)
app.include_router(routes.router)
app.include_router(v1_router)


@app.middleware("http")
async def _request_id(request: Request, call_next):
    import uuid as _uuid
    rid = request.headers.get("X-Request-Id") or f"req_{_uuid.uuid4().hex[:16]}"
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/ready")
def ready():
    """Readiness: DB reachable + storage dir writable. Liveness is /health."""
    from vii.config import get_settings
    from vii.persistence.db import make_engine
    from sqlalchemy import text as _text
    s = get_settings()
    checks: dict[str, bool] = {}
    try:
        engine = make_engine(s.database_url)
        with engine.connect() as conn:
            conn.execute(_text("SELECT 1"))
        engine.dispose()
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        s.storage_dir.mkdir(parents=True, exist_ok=True)
        checks["storage"] = s.storage_dir.is_dir()
    except Exception:
        checks["storage"] = False
    ok = all(checks.values())
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


def run(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    from vii.config import get_settings
    s = get_settings()
    run(s.api_host, s.api_port)
