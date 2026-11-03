"""Persistent background worker: DB-backed async jobs, bounded concurrency.

Replaces blocking in-request `service.run()` calls. Job states live in
`analysis_jobs.status` (queued/running/.../succeeded/failed/cancelled);
progress, failures, retries are persisted so restarts recover. Idempotency:
a job already running/completed is never re-executed by enqueue.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("vii.worker")

TERMINAL = {"succeeded", "failed", "cancelled"}
RUNNING_STATES = {"ingesting", "understanding_video", "transcribing",
                  "extracting_claims", "searching", "assessing", "reporting"}


class Worker:
    """Local-process worker. Redis/Celery optional later; never required."""

    def __init__(self, service, concurrency: int = 2, max_retries: int = 2,
                 on_terminal=None):
        self.service = service
        self.concurrency = max(1, concurrency)
        self.max_retries = max_retries
        # Optional terminal-state callback ``(job_id, status) -> None``,
        # fired exactly once when a job reaches succeeded/failed/cancelled
        # (never on a retryable intermediate failure). Used by the API
        # layer to deliver webhooks for async jobs; omitted = no delivery.
        self.on_terminal = on_terminal
        self._pool: ThreadPoolExecutor | None = None
        self._stop = threading.Event()
        self._inflight: dict[str, object] = {}
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.concurrency,
                                            thread_name_prefix="vii-worker")
            log.info("worker started (concurrency=%d)", self.concurrency)

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
            self._pool = None

    # -- enqueue ---------------------------------------------------------
    def enqueue(self, job_id: str, *, force: bool = False) -> dict:
        """Submit job_id; idempotent — running/terminal jobs are not re-run.

        ``force=True`` is reserved for restart recovery: a job still marked
        in a running state after a process restart has no live executor, so
        recovery resets it to queued and re-submits it. Normal API enqueue
        never uses force and keeps the already-active rejection.
        """
        from vii.domain.enums import JobStatus
        self.start()
        assert self._pool is not None
        with self.service.Session() as db:
            from vii.persistence.repositories import JobRepo
            job = JobRepo(db).get(job_id)
            if job is None:
                raise KeyError(f"unknown job {job_id}")
            if str(job.status) in TERMINAL:
                return {"job_id": job_id, "status": str(job.status),
                        "accepted": False, "reason": "already active or terminal"}
            if str(job.status) in RUNNING_STATES and not force:
                return {"job_id": job_id, "status": str(job.status),
                        "accepted": False, "reason": "already active or terminal"}
            job.status = str(JobStatus.QUEUED)
            db.commit()
        with self._lock:
            if job_id in self._inflight:
                return {"job_id": job_id, "status": "queued",
                        "accepted": False, "reason": "already enqueued"}
            fut = self._pool.submit(self._execute, job_id, 0)
            self._inflight[job_id] = fut
        return {"job_id": job_id, "status": "queued", "accepted": True}

    def cancel(self, job_id: str) -> dict:
        from vii.domain.enums import JobStatus
        from vii.persistence.repositories import JobRepo
        with self.service.Session() as db:
            repo = JobRepo(db)
            job = repo.get(job_id)
            if job is None:
                raise KeyError(f"unknown job {job_id}")
            if str(job.status) in TERMINAL:
                return {"job_id": job_id, "status": str(job.status),
                        "cancelled": False, "reason": "already terminal"}
            repo.set_status(job, JobStatus.CANCELLED)
            repo.log(job_id, "worker", "cancellation requested", "warning")
            status = str(job.status)
        with self._lock:
            owned = job_id in self._inflight
            self._inflight.pop(job_id, None)
        if not owned:
            # No executor will observe this cancellation (job not queued
            # or running here), so the terminal callback fires here;
            # an owning executor fires it instead — exactly once overall.
            self._notify_terminal(job_id, status)
        return {"job_id": job_id, "status": status, "cancelled": True}

    def _notify_terminal(self, job_id: str, status: str) -> None:
        """Fire the terminal callback once; delivery errors never break
        job execution (mirrors webhook delivery: log, never raise)."""
        if self.on_terminal is None:
            return
        try:
            self.on_terminal(job_id, status)
        except Exception as e:
            log.warning("terminal callback failed [%s]: %s", job_id, str(e)[:200])

    # -- execution --------------------------------------------------------
    def _execute(self, job_id: str, attempt: int) -> None:
        from vii.domain.enums import JobStatus
        from vii.persistence.repositories import JobRepo
        try:
            with self.service.Session() as db:
                repo = JobRepo(db)
                job = repo.get(job_id)
                if job is None:
                    return
                if str(job.status) == str(JobStatus.CANCELLED):
                    self._notify_terminal(job_id, str(JobStatus.CANCELLED))
                    return
                repo.set_status(job, JobStatus.INGESTING)

            def _progress(jid: str, status, message: str) -> None:
                if self._stop.is_set():
                    raise RuntimeError("worker shutting down")
                try:
                    with self.service.Session() as db2:
                        repo2 = JobRepo(db2)
                        j = repo2.get(jid)
                        if j is None or str(j.status) == str(JobStatus.CANCELLED):
                            raise RuntimeError("job cancelled")
                        repo2.set_status(j, status)
                except RuntimeError:
                    raise
                except Exception as e:  # progress persistence is best-effort
                    log.warning("progress persist failed [%s]: %s", jid, str(e)[:200])

            self.service.run(job_id, _progress)
            try:
                with self.service.Session() as db:
                    done = JobRepo(db).get(job_id)
                    final = str(done.status) if done is not None else ""
            except Exception:
                final = ""
            if final in TERMINAL:
                self._notify_terminal(job_id, final)
        except Exception as e:
            # Whole-job retries re-run every provider stage (and can
            # re-upload / re-spend). Only retry when the failure is typed
            # retryable or an unknown transient error; configuration,
            # permission, validation, and malformed-response failures are
            # terminal because re-running the same job cannot fix them.
            from vii.errors import ProviderError
            non_retryable = (
                isinstance(e, ValueError)
                or (isinstance(e, ProviderError) and not getattr(e, "retryable", False)))
            retryable = (attempt < self.max_retries and not non_retryable
                         and "cancelled" not in str(e).lower())
            preserved: str | None = None
            failed = False
            try:
                with self.service.Session() as db:
                    repo = JobRepo(db)
                    job = repo.get(job_id)
                    if job is None:
                        return
                    if str(job.status) in (str(JobStatus.SUCCEEDED),
                                           str(JobStatus.CANCELLED)):
                        # Terminal state already persisted (e.g. cancelled
                        # mid-run, or succeeded before a late error): never
                        # overwrite it with FAILED (pipeline parity).
                        preserved = str(job.status)
                        repo.log(job_id, "worker",
                                 f"terminal status {preserved} preserved: "
                                 f"{str(e)[:300]}", "warning")
                    elif retryable:
                        repo.log(job_id, "worker",
                                 f"attempt {attempt + 1} failed: {str(e)[:300]} — retrying",
                                 "warning")
                    else:
                        repo.set_status(job, JobStatus.FAILED)
                        failed = True
                        repo.log(job_id, "worker",
                                 f"failed after {attempt + 1} attempt(s): {str(e)[:500]}",
                                 "error")
            except Exception:
                pass
            if preserved is not None:
                self._notify_terminal(job_id, preserved)
                return
            if failed:
                self._notify_terminal(job_id, str(JobStatus.FAILED))
            if retryable:
                time.sleep(2 * (attempt + 1))
                if not self._stop.is_set():
                    self._execute(job_id, attempt + 1)
                    return
        finally:
            with self._lock:
                self._inflight.pop(job_id, None)

    def recover(self) -> int:
        """Re-enqueue jobs stuck in queued/running states (restart recovery)."""
        from vii.persistence.repositories import JobRepo
        count = 0
        with self.service.Session() as db:
            jobs = JobRepo(db).list(1000)
            stale = [j.id for j in jobs
                     if str(j.status) in RUNNING_STATES or str(j.status) == "queued"]
        for jid in stale:
            try:
                self.enqueue(jid, force=True)
                count += 1
            except Exception:
                continue
        return count
