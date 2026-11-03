"""Entry points: `vii` (desktop), `vii --api` (server), `vii --demo` (explicit synthetic demo),
`vii --validate-dataset [PATH]`, `vii --ingest-dataset [PATH] [--apply]`,
`vii --ingest-only PATH` (local media validation; no job, no provider)."""
from __future__ import annotations

import sys

from vii.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    setup_logging()  # attach secret-redacting filter to all vii.* loggers
    argv = argv if argv is not None else sys.argv[1:]
    if "--api" in argv:
        from vii.api.app import run
        from vii.config import get_settings
        s = get_settings()
        print(f"VII API on http://{s.api_host}:{s.api_port} (docs: /docs)")
        run(s.api_host, s.api_port)
        return 0
    if "--validate-dataset" in argv:
        i = argv.index("--validate-dataset")
        path = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
        return validate_dataset(path)
    if "--ingest-dataset" in argv:
        i = argv.index("--ingest-dataset")
        path = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
        return ingest_dataset(path, apply="--apply" in argv)
    if "--ingest-only" in argv:
        i = argv.index("--ingest-only")
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            print("usage: vii --ingest-only PATH")
            return 2
        return ingest_only(argv[i + 1])
    if "--demo" in argv:
        return demo()
    from vii.ui.main_window import run_app
    return run_app()


def _dataset_path(explicit: str | None):
    from pathlib import Path
    from vii.config import get_settings
    return Path(explicit) if explicit else get_settings().dataset_csv_path


def validate_dataset(path: str | None = None) -> int:
    """Validate the dataset CSV and print a JSON report. Exit 0 when the
    file is valid or absent (absence is a normal pre-dataset state); exit 2
    when the file exists but has schema/row errors."""
    import json as _json
    from vii.dataset.ingestion import validate_csv
    report = validate_csv(_dataset_path(path))
    print(_json.dumps(report.as_dict(), indent=2))
    return 0 if report.ok or not report.exists else 2


def ingest_dataset(path: str | None = None, apply: bool = False) -> int:
    """Dry-run by default; --apply registers rows into the Dataset Inbox.

    Never starts video analysis. Exit 2 when validation fails."""
    import json as _json
    from vii.dataset.ingestion import ingest_csv
    from vii.persistence.db import init_db
    from vii.config import get_settings
    s = get_settings()
    session_factory = init_db(s.database_url, s.storage_dir)
    result = ingest_csv(_dataset_path(path), session_factory,
                        s.consumer_id or "default", dry_run=not apply)
    print(_json.dumps(result.as_dict(), indent=2))
    return 0 if result.report.ok else 2


def ingest_only(path: str) -> int:
    """Validate + hash one local media file. Exit 0 = valid, 2 = rejected.

    Ingestion-only by construction: no database is opened, no analysis job
    is created, no worker is enqueued, and no provider module is imported.
    Prints the MediaIngestionResult (or the typed rejection) as JSON.
    """
    import json as _json

    from vii.config import get_settings
    from vii.media.ingestion import inspect_local_media

    try:
        s = get_settings()
        result = inspect_local_media(path, s.max_upload_mb, s.max_video_seconds,
                                     s.ffprobe_bin)
    except ValueError as e:
        print(_json.dumps({"ok": False, "error": type(e).__name__,
                           "message": str(e)}, indent=2))
        return 2
    print(_json.dumps({"ok": True, **result.model_dump()}, indent=2))
    return 0


def demo() -> int:
    """Headless SYNTHETIC demo run (explicit opt-in via --demo).

    Uses deterministic fixtures only; this is not real provider-backed
    analysis and is labeled as such in every output."""
    from vii.application.services import AnalysisService
    from vii.config import Settings
    from vii.domain.schemas import AnalysisCreate
    import tempfile, os
    tmp = tempfile.mkdtemp(prefix="vii_demo_")
    s = Settings(VII_DEMO_MODE=True, VII_DATABASE_URL=f"sqlite:///{tmp}/vii.db",
                 VII_STORAGE_DIR=tmp)
    svc = AnalysisService(s)
    jid = svc.create(AnalysisCreate(source={"kind": "public_url",
                                            "url": "https://example.com/demo-video.mp4"},
                                    title="Synthetic demo", demo=True))
    payload = svc.run(jid)
    print(f"job={jid}")
    for c in payload["claims"]:
        print(f"  [{c['status']}] {c['text'][:80]}")
    print(f"exports in {tmp}/exports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
