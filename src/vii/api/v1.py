"""Versioned v1 REST API: analyses, jobs, investigate, compare, datasets.

Auth: Bearer service key when VII_REQUIRE_AUTH=true, else consumer header
passthrough. All job/dataset access is scoped to the calling consumer,
cross-consumer reads return 404, never another consumer's data. Streaming
webhook delivery: POST /v1/analyses accepts an optional webhook_url and
fires a signed JSON POST when the job reaches a terminal state. Delivery
is DISABLED by default (VII_WEBHOOK_ENABLED=true to enable) and targets
are SSRF-validated (no localhost/private/link-local/metadata, no
redirects); disabled or invalid targets are stashed but never posted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from vii.application.services import AnalysisService
from vii.config import get_settings
from vii.domain.schemas import (
    AnalysisCreate,
    CompareRequest,
    DatasetRegisterRequest,
    InvestigateRequest,
)
from vii.errors import ProviderConfigurationError, ProviderError

log = logging.getLogger("vii.api.v1")
router = APIRouter(prefix="/v1")

_service: AnalysisService | None = None
_worker = None
_singleton_lock = threading.Lock()

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_job_path(storage_dir, job_id: str, ext: str):
    """Report path for a job, scoped under the exports directory."""
    if not _JOB_ID_RE.match(job_id or ""):
        return None
    base = (Path(storage_dir) / "exports").resolve()
    path = (base / f"{job_id}.{ext}").resolve()
    return path if path.is_relative_to(base) else None


def sanitize_consumer(name: str) -> str:
    """Filesystem-safe consumer id (DB identity is unchanged)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    cleaned = cleaned.replace("..", "_").strip(".")
    return cleaned[:128] or "default"


def svc() -> AnalysisService:
    global _service
    if _service is None:
        with _singleton_lock:
            if _service is None:
                _service = AnalysisService(get_settings())
    return _service


def _terminal_webhook(job_id: str, status: str) -> None:
    """Worker terminal callback: deliver the stashed webhook for async
    jobs (the sync /run path fires _fire_webhook directly). The consumer
    comes from the job row; delivery itself no-ops when webhooks are
    disabled or no target was stashed, never raises into the worker."""
    consumer = "default"
    try:
        from vii.persistence.repositories import JobRepo
        with svc().Session() as db:
            job = JobRepo(db).get(job_id)
            if job is not None:
                consumer = str(job.consumer) or "default"
    except Exception:
        pass
    _fire_webhook(job_id, status, consumer)


def worker():
    global _worker
    if _worker is None:
        with _singleton_lock:
            if _worker is None:
                from vii.application.worker import Worker
                s = get_settings()
                _worker = Worker(svc(), s.worker_concurrency,
                                 on_terminal=_terminal_webhook)
    return _worker


def consumer_id(authorization: str | None = Header(default=None),
                x_consumer: str | None = Header(default=None,
                                                alias="X-Consumer")) -> str:
    s = get_settings()
    if s.require_auth:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing Bearer service key")
        ok, cid = s.check_api_key(authorization[len("Bearer "):].strip())
        if not ok:
            raise HTTPException(403, "invalid service key")
        return cid
    if x_consumer:
        return sanitize_consumer(x_consumer)
    return s.consumer_id or "default"


# -- service ------------------------------------------------------------
@router.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "live_mode": s.live_mode, "offline_mode": s.offline_mode,
            "model": s.meta_model, "api_version": "v1"}


@router.get("/diagnostics")
def diagnostics(auth: str = Depends(consumer_id)):
    return svc().diagnostics()


# -- analyses -----------------------------------------------------------
@router.post("/analyses", status_code=201)
def create_analysis(req: AnalysisCreate, auth: str = Depends(consumer_id),
                    webhook_url: str | None = None):
    try:
        job_id = svc().create(req, auth)
    except ProviderConfigurationError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    try:
        worker().enqueue(job_id)
    except Exception as e:  # enqueue failure surfaces honestly
        raise HTTPException(500, f"job created but enqueue failed: {e}") from e
    webhook_accepted = False
    if webhook_url:
        _stash_webhook(job_id, webhook_url, auth)
        ok, reason = _webhook_target_ok(webhook_url)
        webhook_accepted = bool(get_settings().webhook_enabled and ok)
        if not webhook_accepted:
            log.warning("webhook for job %s not armed (%s)", job_id, reason)
    return {"job_id": job_id, "status": "queued", "webhook": webhook_accepted}


@router.post("/analyses/{job_id}/run")
def run_sync(job_id: str, auth: str = Depends(consumer_id)):
    """Synchronous run (small jobs). Long jobs should use POST /analyses."""
    if not svc().get(job_id, auth):
        raise HTTPException(404, "unknown job")
    try:
        out = svc().run(job_id)
        _fire_webhook(job_id, "succeeded", auth)
        return out
    except ProviderConfigurationError as e:
        raise HTTPException(503, str(e)) from e
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.get("/jobs/{job_id}")
def get_job(job_id: str, auth: str = Depends(consumer_id)):
    d = svc().get(job_id, auth)
    if not d:
        raise HTTPException(404, "unknown job")
    return d


@router.get("/analyses/{job_id}")
def get_analysis(job_id: str, auth: str = Depends(consumer_id)):
    d = svc().get(job_id, auth)
    if not d:
        raise HTTPException(404, "unknown job")
    return d


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, auth: str = Depends(consumer_id)):
    if not svc().get(job_id, auth):
        raise HTTPException(404, "unknown job")
    return worker().cancel(job_id)


@router.get("/analyses/{job_id}/report")
def get_report_json(job_id: str, auth: str = Depends(consumer_id)):
    d = svc().get(job_id, auth)
    if not d:
        raise HTTPException(404, "unknown job")
    s = get_settings()
    path = _safe_job_path(s.storage_dir, job_id, "json")
    if path is None or not path.exists():
        raise HTTPException(404, "report not generated yet, poll the job until succeeded")
    return JSONResponse(json.loads(path.read_text()))


@router.get("/analyses/{job_id}/report.md", response_class=PlainTextResponse)
def get_report_md(job_id: str, auth: str = Depends(consumer_id)):
    if not svc().get(job_id, auth):
        raise HTTPException(404, "unknown job")
    s = get_settings()
    path = _safe_job_path(s.storage_dir, job_id, "md")
    if path is None or not path.exists():
        raise HTTPException(404, "report not generated yet, poll the job until succeeded")
    return path.read_text()


# -- uploads -------------------------------------------------------------
@router.post("/uploads", status_code=201)
def upload_video(file: UploadFile = File(...), auth: str = Depends(consumer_id)):  # noqa: B008
    """Multipart local-video upload -> stored original -> ready for /v1/analyses.

    Streams in 1 MiB chunks and aborts past VII_MAX_UPLOAD_MB (deleting the
    partial file) instead of buffering the whole upload in memory.
    """
    s = svc().settings
    suffix = Path(file.filename or "upload").suffix.lower() or ".mp4"
    if suffix not in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"):
        raise HTTPException(400, f"unsupported format {suffix}")
    name = f"{sanitize_consumer(auth)}_{uuid.uuid4().hex[:12]}{suffix}"
    dest = Path(s.storage_dir) / "originals" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = s.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"file too large: exceeds {s.max_upload_mb}MB limit")
                out.write(chunk)
    except HTTPException:
        raise
    # Content check: the extension claim must match the actual container
    # signature; a renamed non-video file is deleted and rejected.
    from vii.media.ingestion import _CONTAINER_FAMILY, _EXT_CONTAINER, sniff_container
    container = sniff_container(dest)
    expected = _EXT_CONTAINER.get(suffix, "unknown")
    if written == 0 or container == "unknown" or (
            _CONTAINER_FAMILY.get(container) != _CONTAINER_FAMILY.get(expected)):
        dest.unlink(missing_ok=True)
        raise HTTPException(
            400, f"upload content does not match {suffix} container signature")
    size_mb = written / (1024 * 1024)
    from vii.media.hashing import sha256_file
    digest = sha256_file(dest)
    return {"storage_ref": str(dest), "sha256": digest, "size_mb": round(size_mb, 2),
            "filename": file.filename, "consumer": auth}


# -- investigate ----------------------------------------------------------
@router.post("/search/investigate")
def investigate(req: InvestigateRequest, auth: str = Depends(consumer_id)):
    """Adaptive per-claim evidence investigation (Meta web_search when live)."""
    from vii.evidence import retrieval
    s = get_settings()
    # Live path goes through the shared retrieval layer (same as pipeline).
    live_client = svc().pipeline.client if s.live_mode else None
    res = retrieval.search_claim(req.query, req.claim_id or "q", s, live_client)
    items = [{"url": r.url, "title": r.title, "snippet": r.snippet,
              "publisher": r.publisher, "method": r.method.value,
              "response_id": r.search_response_id} for r in res["results"]]
    cits = [{"url": c.url, "span": c.cited_span} for c in res["citations"]]
    return {"performed": res["performed"], "offline": res["offline"],
            "note": res["note"], "results": items, "citations": cits,
            "query": req.query, "consumer": auth}


# -- compare ---------------------------------------------------------------
@router.post("/content/compare")
def compare(req: CompareRequest, auth: str = Depends(consumer_id)):
    """Reused-asset comparison: exact SHA-256 + perceptual-hash distance.

    Precedence: explicit SHA pair > report-backed job pair. For job pairs the
    endpoint reads persisted reports (consumer-scoped) and compares their
    originality dimensions, never the other consumer's raw media.
    """
    from vii.media.hashing import phash_distance
    from vii.persistence.repositories import AnalysisRepo
    out: dict = {"exact_match": False, "phash": None, "notes": ""}
    if req.reference_sha256 and req.candidate_sha256:
        out["exact_match"] = (req.reference_sha256.strip().lower()
                              == req.candidate_sha256.strip().lower())
        out["notes"] = ("Exact duplicate (SHA-256 match)." if out["exact_match"]
                        else "Different SHA-256 digests; near-duplicate check needs "
                             "frame perceptual hashes from completed analyses.")
        return out
    if req.reference_job_id and req.candidate_job_id:
        ref = svc().get(req.reference_job_id, auth)
        if not ref:
            raise HTTPException(404, "unknown reference job")
        cand = svc().get(req.candidate_job_id, auth)
        if not cand:
            raise HTTPException(404, "unknown candidate job")
        with svc().Session() as db:
            repo = AnalysisRepo(db)
            r_rep = repo.report_payload(req.reference_job_id) or {}
            c_rep = repo.report_payload(req.candidate_job_id) or {}
        if not r_rep or not c_rep:
            raise HTTPException(409, "one or both jobs have no persisted JSON report yet, "
                                     "run them to completion first")
        r_o = (r_rep.get("dimensions") or {}).get("originality") or {}
        c_o = (c_rep.get("dimensions") or {}).get("originality") or {}
        r_sha, c_sha = (r_o.get("sha256") or "").lower(), (c_o.get("sha256") or "").lower()
        out["exact_match"] = bool(r_sha and r_sha == c_sha)
        dists: list[int] = []
        for rh in r_o.get("phashes") or []:
            for ch in c_o.get("phashes") or []:
                d = phash_distance(str(rh), str(ch))
                if d is not None:
                    dists.append(d)
        if dists:
            out["phash"] = {"min_distance": min(dists), "comparisons": len(dists)}
        out["notes"] = ("Exact duplicate (stored SHA-256 match).",
                        "No exact SHA-256 match in stored reports; "
                        f"phash signal: {out['phash']}." if out["phash"] else
                        "No exact SHA-256 match in stored reports; no shared corpus "
                        "records to measure perceptual distance.")[not out["exact_match"]]
        out["reference_job"] = req.reference_job_id
        out["candidate_job"] = req.candidate_job_id
        return out
    out["notes"] = ("Provide reference_sha256 + candidate_sha256 for an exact "
                    "check, or two completed job ids for report-level comparison.")
    return out


# -- datasets ---------------------------------------------------------------
@router.post("/datasets/samples", status_code=201)
def register_sample(req: DatasetRegisterRequest, auth: str = Depends(consumer_id)):
    """Register a video in the consumer's Unclassified Dataset Inbox."""
    from vii.media import social as social_mod
    from vii.persistence.repositories import DatasetRepo
    platform = req.platform
    if not platform and req.source_url:
        platform = social_mod.classify_url(req.source_url).get("platform", "")
    storage_ref, sha, dur, meta = req.storage_ref, "", 0.0, {}
    if req.local_path:
        from vii.media.hashing import sha256_file
        p = Path(req.local_path)
        # Path-boundary guard: server-side local_path may only reference
        # files already under the operator's storage dir (e.g. prior
        # /v1/uploads output). Arbitrary paths like /etc/passwd or another
        # tenant's files are refused; use /v1/uploads for new files.
        storage_root = Path(svc().settings.storage_dir).resolve()
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        if not resolved.is_relative_to(storage_root):
            raise HTTPException(400, "local_path must be under VII_STORAGE_DIR; "
                                     "upload new files via /v1/uploads instead")
        p = resolved
        if not p.is_file():
            raise HTTPException(400, f"local file not found: {req.local_path}")
        sha = sha256_file(p)
        dur = 0.0
        try:
            from vii.media import ffmpeg as ff
            meta = ff.metadata_summary(ff.probe(p, svc().settings.ffprobe_bin))
            dur = float(meta.get("duration_s", 0) or 0)
        except Exception:
            meta = {"probe": "unavailable"}
        dest = Path(svc().settings.storage_dir) / "datasets" / sanitize_consumer(auth) / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        storage_ref = str(dest)
    with svc().Session() as db:
        row = DatasetRepo(db).register(auth, req.video_id, req.source_url,
                                       platform, storage_ref, sha, dur, meta)
        return {"sample_id": row.id, "video_id": row.video_id,
                "annotation_status": row.annotation_status,
                "storage_ref": storage_ref, "sha256": sha,
                "platform": platform, "consumer": auth}


@router.get("/datasets/search")
def search_datasets(q: str = "", limit: int = 20,
                    auth: str = Depends(consumer_id)):
    from vii.persistence.repositories import DatasetRepo
    with svc().Session() as db:
        rows = DatasetRepo(db).search(auth, q, limit)
        return [{"sample_id": r.id, "video_id": r.video_id,
                 "source_url": r.source_url, "platform": r.platform,
                 "sha256": r.sha256, "annotation_status": r.annotation_status,
                 "storage_ref": r.storage_ref} for r in rows]


@router.get("/datasets/check")
def check_dataset_csv(auth: str = Depends(consumer_id)):
    """Validate the configured dataset CSV (read-only, no DB writes, no analysis).

    Uses Settings.dataset_csv_path (DATASET_CSV_PATH, default
    data/dataset.csv). A missing file is a normal 200 with exists=false,
    the app runs without a dataset until one is supplied.
    """
    from vii.dataset.ingestion import validate_csv
    s = get_settings()
    return validate_csv(s.dataset_csv_path).as_dict()


@router.post("/datasets/ingest-csv")
def ingest_dataset_csv(dry_run: bool = True, auth: str = Depends(consumer_id)):
    """Validate and (unless dry_run) register CSV rows into the caller's inbox.

    Idempotent per (consumer, video_id); never starts video analysis.
    Defaults to dry_run=true so a plain POST is a safe preview.
    """
    from vii.dataset.ingestion import ingest_csv
    s = get_settings()
    result = ingest_csv(s.dataset_csv_path, svc().Session, auth, dry_run=dry_run)
    return result.as_dict()


@router.get("/datasets/samples/{sample_id}")
def get_sample(sample_id: str, auth: str = Depends(consumer_id)):
    import json as _json

    from vii.persistence.repositories import DatasetRepo
    with svc().Session() as db:
        row = DatasetRepo(db).get(sample_id, auth)
        if not row:
            raise HTTPException(404, "unknown sample")
        return {"sample_id": row.id, "video_id": row.video_id,
                "source_url": row.source_url, "platform": row.platform,
                "storage_ref": row.storage_ref, "sha256": row.sha256,
                "duration_s": row.duration_s,
                "meta": _json.loads(row.meta_json or "{}"),
                "fingerprint": _json.loads(row.fingerprint_json or "{}"),
                "annotation_status": row.annotation_status,
                "labels": _json.loads(row.labels_json or "[]")}


# -- webhooks ---------------------------------------------------------------
# Disabled by default (VII_WEBHOOK_ENABLED). When enabled, targets must be
# public https/http hosts: localhost, private, link-local, cloud-metadata,
# and redirect responses are all refused. Validation resolves the hostname
# twice (pre-request and post-response) to narrow DNS-rebinding bypasses;
# delivery failures are logged, never raised into job execution.

_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254", "100.100.100.200"}


def _webhook_target_ok(url: str) -> tuple[bool, str]:
    """Validate a webhook target. Returns (ok, reason)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    try:
        parts = urlparse((url or "").strip())
    except Exception:
        return False, "unparseable URL"
    if parts.scheme not in ("https", "http"):
        return False, "only https/http targets allowed"
    host = (parts.hostname or "").lower()
    if not host:
        return False, "no host"
    if host in ("localhost",) or host.endswith(".localhost"):
        return False, "localhost targets refused"
    if host.endswith((".internal", ".local", ".lan", ".corp")):
        return False, "internal hostnames refused"
    try:
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return False, "hostname does not resolve"
        for _fam, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global or str(ip) in _METADATA_IPS:
                return False, f"non-public destination ({ip})"
    except socket.gaierror:
        return False, "hostname does not resolve"
    except Exception as e:
        return False, f"resolution failed: {e}"
    return True, "ok"


def _webhook_host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _stash_webhook(job_id: str, url: str, consumer: str) -> None:
    s = get_settings()
    d = Path(s.storage_dir) / "tmp" / "webhooks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{job_id}.json").write_text(json.dumps(
        {"url": url, "consumer": consumer}))


def _fire_webhook(job_id: str, status: str, consumer: str) -> None:
    import urllib.request
    s = get_settings()
    if not s.webhook_enabled:
        return
    f = Path(s.storage_dir) / "tmp" / "webhooks" / f"{job_id}.json"
    if not f.exists():
        return
    try:
        spec = json.loads(f.read_text())
        target = spec.get("url", "")
        ok, reason = _webhook_target_ok(target)
        if not ok:
            log.warning("webhook for job %s refused (%s)", job_id, reason)
            return
        expected_host = _webhook_host_of(target)
        body = json.dumps({"job_id": job_id, "status": status,
                           "consumer": consumer}).encode()
        secret = (s.webhook_secret or "vii-webhook").encode()
        sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

        class _Guard(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None  # refuse all redirects

        opener = urllib.request.build_opener(_Guard)
        req = urllib.request.Request(target, data=body,
                                     headers={"Content-Type": "application/json",
                                              "X-VII-Signature": f"sha256={sig}"},
                                     method="POST")
        with opener.open(req, timeout=10) as resp:
            final_host = _webhook_host_of(resp.geturl())
            if final_host != expected_host:
                log.warning("webhook for job %s refused (redirected host)", job_id)
                return
            ok2, reason2 = _webhook_target_ok(resp.geturl())
            if not ok2:
                log.warning("webhook for job %s refused post-response (%s)",
                            job_id, reason2)
                return
            resp.read()  # nosec: SSRF-validated target, bounded, redirects refused
    except Exception as e:
        log.warning("webhook delivery failed [%s]: %s", job_id, str(e)[:200])
