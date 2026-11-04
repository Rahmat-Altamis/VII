"""Worker terminal-state handling: cancellation preservation (Bug 2) and
the on_terminal callback that drives async webhooks (Bug 4).

All runs use a fake service.run against a real (demo-mode, SQLite) job
store, no provider calls, no network, no credits.
"""
from __future__ import annotations


def _make_job(settings):
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate

    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    return svc, jid


def _status(svc, jid) -> str:
    from vii.persistence.repositories import JobRepo

    with svc.Session() as db:
        job = JobRepo(db).get(jid)
        return str(job.status) if job is not None else "missing"


def _set_status(svc, jid, status) -> None:
    from vii.persistence.repositories import JobRepo

    with svc.Session() as db:
        repo = JobRepo(db)
        repo.set_status(repo.get(jid), status)


def _raise(exc):
    def _run(job_id, progress=None):
        raise exc
    return _run


# -- Bug 2: terminal states survive the worker exception path --------------

def test_worker_preserves_cancelled_when_run_raises(settings):
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    svc, jid = _make_job(settings)

    def cancelled_mid_run(job_id, progress=None):
        _set_status(svc, job_id, JobStatus.CANCELLED)
        raise RuntimeError("job cancelled")

    svc.run = cancelled_mid_run
    Worker(svc, max_retries=0)._execute(jid, 0)
    assert _status(svc, jid) == "cancelled"


def test_worker_preserves_succeeded_when_run_raises_after(settings):
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    svc, jid = _make_job(settings)

    def succeeded_then_raises(job_id, progress=None):
        _set_status(svc, job_id, JobStatus.SUCCEEDED)
        raise RuntimeError("late failure after success was persisted")

    svc.run = succeeded_then_raises
    Worker(svc, max_retries=0)._execute(jid, 0)
    assert _status(svc, jid) == "succeeded"


def test_worker_marks_failed_when_run_raises(settings):
    svc, jid = _make_job(settings)
    from vii.application.worker import Worker

    svc.run = _raise(ValueError("boom"))
    Worker(svc, max_retries=0)._execute(jid, 0)
    assert _status(svc, jid) == "failed"


# -- Bug 4: on_terminal fires exactly once per terminal outcome ------------

def test_on_terminal_fires_once_on_success(settings):
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    svc, jid = _make_job(settings)
    calls: list = []
    svc.run = lambda job_id, progress=None: _set_status(svc, job_id, JobStatus.SUCCEEDED)
    Worker(svc, max_retries=0,
           on_terminal=lambda j, s: calls.append((j, s)))._execute(jid, 0)
    assert calls == [(jid, "succeeded")]


def test_on_terminal_fires_once_on_failure(settings):
    from vii.application.worker import Worker

    svc, jid = _make_job(settings)
    calls: list = []
    svc.run = _raise(ValueError("boom"))
    Worker(svc, max_retries=0,
           on_terminal=lambda j, s: calls.append((j, s)))._execute(jid, 0)
    assert calls == [(jid, "failed")]
    assert _status(svc, jid) == "failed"


def test_on_terminal_fires_once_on_cancelled(settings):
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    svc, jid = _make_job(settings)
    calls: list = []

    def cancelled_mid_run(job_id, progress=None):
        _set_status(svc, job_id, JobStatus.CANCELLED)
        raise RuntimeError("job cancelled")

    svc.run = cancelled_mid_run
    Worker(svc, max_retries=0,
           on_terminal=lambda j, s: calls.append((j, s)))._execute(jid, 0)
    assert calls == [(jid, "cancelled")]
    assert _status(svc, jid) == "cancelled"


def test_on_terminal_not_fired_before_terminal_retry(settings, monkeypatch):
    import vii.application.worker as worker_mod
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    monkeypatch.setattr(worker_mod.time, "sleep", lambda _s: None)
    svc, jid = _make_job(settings)
    calls: list = []
    attempts: list = []

    def flaky(job_id, progress=None):
        attempts.append(job_id)
        if len(attempts) == 1:
            raise RuntimeError("transient failure")
        _set_status(svc, job_id, JobStatus.SUCCEEDED)

    svc.run = flaky
    Worker(svc, max_retries=1,
           on_terminal=lambda j, s: calls.append((j, s)))._execute(jid, 0)
    assert len(attempts) == 2
    assert calls == [(jid, "succeeded")]  # once, only at the terminal attempt


def test_worker_without_callback_completes_without_error(settings):
    from vii.application.worker import Worker
    from vii.domain.enums import JobStatus

    svc, jid = _make_job(settings)
    svc.run = lambda job_id, progress=None: _set_status(svc, job_id, JobStatus.SUCCEEDED)
    Worker(svc, max_retries=0)._execute(jid, 0)  # on_terminal omitted
    assert _status(svc, jid) == "succeeded"

    svc2, jid2 = _make_job(settings)
    svc2.run = _raise(ValueError("boom"))
    Worker(svc2, max_retries=0)._execute(jid2, 0)
    assert _status(svc2, jid2) == "failed"


def test_v1_worker_wires_terminal_callback_to_webhook(settings, monkeypatch):
    import vii.api.v1 as v1

    svc, jid = _make_job(settings)
    fired: list = []
    monkeypatch.setattr(v1, "_fire_webhook",
                        lambda job_id, status, consumer: fired.append(
                            (job_id, status, consumer)))
    monkeypatch.setattr(v1, "_service", svc)
    monkeypatch.setattr(v1, "_worker", None)
    monkeypatch.setattr(v1, "get_settings", lambda: settings)
    try:
        w = v1.worker()
        assert w.on_terminal is not None
        w.on_terminal(jid, "succeeded")
    finally:
        monkeypatch.setattr(v1, "_worker", None)
    assert fired == [(jid, "succeeded", "default")]


def test_fire_webhook_posts_signed_payload_once(tmp_path, monkeypatch):
    import vii.api.v1 as v1
    from vii.config import Settings

    s = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                 VII_WEBHOOK_ENABLED=True, VII_STORAGE_DIR=tmp_path)
    monkeypatch.setattr(v1, "get_settings", lambda: s)
    monkeypatch.setattr(v1, "_webhook_target_ok", lambda url: (True, "ok"))
    v1._stash_webhook("job_wh", "https://hooks.example.com/vii", "default")

    posts: list = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def geturl(self):
            return "https://hooks.example.com/vii"

        def read(self):
            return b""

    class _Opener:
        def open(self, req, timeout=None):
            posts.append(req)
            return _Resp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: _Opener())
    v1._fire_webhook("job_wh", "succeeded", "default")
    assert len(posts) == 1
    assert posts[0].get_header("X-vii-signature", "").startswith("sha256=")
    import json as _json
    body = _json.loads(posts[0].data.decode())
    assert body == {"job_id": "job_wh", "status": "succeeded",
                    "consumer": "default"}
