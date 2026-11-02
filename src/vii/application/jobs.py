"""Qt-friendly background runner (QThread worker calls service.run)."""
from __future__ import annotations

import threading


class JobRunner:
    """Runs pipeline.run in a thread; UI passes a Qt-signal-safe progress callback."""

    def __init__(self, service):
        self.service = service
        self._cancelled: set[str] = set()

    def cancel(self, job_id: str):
        self._cancelled.add(job_id)

    def run_async(self, job_id: str, progress=None, done=None):
        def _target():
            try:
                result = self.service.run(job_id, progress)
                if done: done(job_id, result, None)
            except Exception as e:  # noqa: BLE001 — surfaced to UI
                if done: done(job_id, None, e)
        t = threading.Thread(target=_target, daemon=True)
        t.start()
        return t
