# Development Guide

## Setup

```bash
cd video-integrity-intelligence
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # API + tests + Ruff; add ,desktop for PySide6 UI
cp .env.example .env             # set MODEL_API_KEY for real (online-first) analysis
which ffmpeg ffprobe             # media tools (required for local-file probing)
```

## Run

```bash
./scripts/run_api.sh             # FastAPI on http://127.0.0.1:8765 (docs: /docs)
./scripts/run_demo.sh            # headless offline end-to-end (synthetic fixture)
./scripts/run_ui.sh              # PySide6 desktop (needs .[desktop])
python3 -m vii.main --validate-dataset   # dataset CSV check (see docs/DATASET.md)
```

Without `MODEL_API_KEY`, provider-backed analysis fails explicitly with
`ProviderConfigurationError` (job marked `failed`) — fixtures are never
substituted. A synthetic demo runs only on explicit opt-in
(`VII_DEMO_MODE=true`, `--demo`, or `demo=true`) and is labeled SYNTHETIC DEMO.
Live mode needs `MODEL_API_KEY` (+ optional `META_BASE_URL`, `META_MODEL`).

## Test & lint

```bash
python3 -m pytest tests/ -q      # unit + integration + API tests (mocks only)
ruff check src tests             # lint (config in pyproject.toml [tool.ruff])
```

Live Meta checks (video URL, file upload, web search, transcription) are
**opt-in and never run by default** — they need a real key and spend credits.
Routine CI uses mocked provider responses only.

## Database & migrations

```bash
# Zero-config dev: vii.persistence.db.init_db creates tables automatically.
# Reproducible schema (preferred for shared/production DBs):
VII_DATABASE_URL=sqlite:///./data/vii.db alembic upgrade head
alembic downgrade -1             # roll back one revision
```

Revision `0001_initial` creates the 12 tables in `vii.persistence.models`.
`alembic/env.py` resolves the URL as: `-x url=` → `VII_DATABASE_URL` →
`sqlite:///./data/vii.db`. PostgreSQL is model-compatible only: no PostgreSQL
driver is declared in `pyproject.toml`, so PostgreSQL URLs do not run on a
standard install (see `docs/TECH_STACK.md` §5/§7).

## Layout (where to put new code)

- HTTP concerns → `src/vii/api/` (v1 router is the contract).
- Use cases/orchestration → `src/vii/application/` (`services.py` facade,
  `pipeline.py` stages, `worker.py` lifecycle).
- Pure contracts → `src/vii/domain/` (no Qt/SQL/HTTP imports allowed).
- DB access → `src/vii/persistence/repositories.py` only.
- Vendor I/O → `src/vii/meta/` (adapter) — never in handlers or pipeline.
- CSV data → `src/vii/dataset/`; reports → `src/vii/reports/`.

## Configuration

All settings are env-driven via `vii.config.Settings` (aliases in
`.env.example`). Validated at startup: `VII_REQUIRE_AUTH=true` without keys,
or a non-loopback bind without auth, **fails fast** instead of running
exposed. Secrets are redacted in logs (`vii.logging_setup`) and diagnostics
(`Settings.redacted()`).

## Troubleshooting

- `ffprobe not found` → install FFmpeg; URL/offline flows still work.
- Tests touching settings: clear the cache (`get_settings.cache_clear()`)
  after changing env vars in a test process — see `tests/test_auth_hardening.py`.
- Stale jobs after a crash: restart the API; the worker recovers
  `queued`/running jobs automatically (`Worker.recover`).
