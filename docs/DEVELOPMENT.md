# Development Guide

## Setup

```bash
git clone https://github.com/Rahmat-Altamis/VII.git
cd VII
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
which ffmpeg ffprobe
```

Notes on the commands above. The dev extra includes the full app plus
tests plus Ruff. Add the desktop extra for the PySide6 UI. Set
MODEL_API_KEY in `.env` for real online first analysis. The ffmpeg and
ffprobe binaries are required for local file probing.

Library consumers need only the core install plus the extras for the
features they use (`.[api]`, `.[db]`, `.[provider]`, `.[media]`,
`.[mcp]`, or `.[app]` for all of them; see `pyproject.toml`). Basic
library usage (`from vii import VII`, plus `inspect_media`, `sha256`,
`assess_originality`, `validate_dataset`) requires no deployed server,
database, or background worker.

## Run

```bash
.venv/bin/vii tui
.venv/bin/vii check <video> --quick
./scripts/run_api.sh
./scripts/run_demo.sh
python3 -m vii.main --validate-dataset
```

The TUI is the interactive agent console. The quick flag prints a fast
local screen. The API script serves FastAPI on 127.0.0.1:8765 with
interactive docs at /docs. The demo script runs a headless synthetic
run. The validate command checks the dataset CSV (see docs/DATASET.md).

Without `MODEL_API_KEY`, provider backed analysis fails explicitly
with `ProviderConfigurationError` (job marked `failed`). Fixtures are
never substituted. A synthetic demo runs only on explicit opt in
(`VII_DEMO_MODE=true`, the demo flag, or `demo=true`) and is labeled
SYNTHETIC DEMO. Live mode needs `MODEL_API_KEY` plus optional
`META_BASE_URL` and `META_MODEL`.

## Test and lint

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src tests
```

The suite (255 tests) uses mocked providers only, so routine runs
spend no credits. Live provider checks are opt in and never run by
default. They need a real key and spend credits.

## Database and migrations

```bash
VII_DATABASE_URL=sqlite:///./data/vii.db alembic upgrade head
alembic downgrade -1
```

Zero config dev happens through `vii.persistence.db.init_db`, which
creates tables automatically and then applies idempotent startup
migrations. Alembic revisions are the reproducible path for shared or
production databases. Revision `0002_evidence_relationship` adds the
evidence relationship columns. `alembic/env.py` resolves the URL from
the `-x url` option, then `VII_DATABASE_URL`, then the default SQLite
path. PostgreSQL is model compatible only: no PostgreSQL driver ships
in `pyproject.toml`, so PostgreSQL URLs do not run on a standard
install (see `docs/TECH_STACK.md`).

## Layout (where to put new code)

1. HTTP concerns go in `src/vii/api/` (the v1 router is the contract).
2. Use cases and orchestration go in `src/vii/application/`
   (`services.py` facade, `pipeline.py` stages, `worker.py` lifecycle).
3. Pure contracts go in `src/vii/domain/` (no Qt, SQL, or HTTP imports).
4. All DB access goes in `src/vii/persistence/repositories.py` only.
5. Vendor I/O goes in `src/vii/meta/` (the adapter), never in handlers
   or pipeline code.
6. CSV data goes in `src/vii/dataset/`; reports go in `src/vii/reports/`.
7. Terminal surfaces live in `src/vii/tui.py`, `src/vii/cli.py`, and
   `src/vii/checker.py`. Agent tools live in `src/vii/mcp_server.py`.

## Configuration

All settings are env driven through `vii.config.Settings` (aliases in
`.env.example`). Validated at startup: `VII_REQUIRE_AUTH=true` without
keys, or a loopback bypass bind without auth, fails fast instead of
running exposed. Secrets are redacted in logs (`vii.logging_setup`)
and diagnostics (`Settings.redacted()`).

## Troubleshooting

1. `ffprobe not found`: install FFmpeg. URL flows still work.
2. Tests touching settings: clear the cache
   (`get_settings.cache_clear()`) after changing env vars in a test
   process. See `tests/test_auth_hardening.py`.
3. Stale jobs after a crash: restart the API. The worker recovers
   queued and running jobs automatically (`Worker.recover`).
