# VII: Technology Stack
### Why each tool was chosen, where it is used, and what is verified

**VII is an API-first, modular-monolith, evidence-oriented video-integrity engine. Every technology below is listed only where the code actually imports or configures it — a listed technology is not proof that its workflow works end to end, and no integration is claimed verified without executed evidence.**

## 1. Selection principles

- **API-first, modular monolith.** One Python process (`vii.api.app:run`) plus an optional desktop UI; no microservices, broker, or orchestration layer without a demonstrated need.
- **No dependency without a demonstrated need.** If a package is declared but never imported, it is flagged in §9, not presented as selected.
- **PostgreSQL-compatible persistence.** Portable SQLAlchemy 2 models with SQLite as the zero-config default (see §5 for the driver caveat).
- **Reproducible and testable.** Mocked provider responses for routine tests; live calls are opt-in only.
- **Online-first.** Real provider-backed analysis is the default. A missing key, invalid credentials, or a failed provider request produces a typed error (`ProviderConfigurationError`/`ProviderError` in `src/vii/errors.py`) and a failed job — never fixture output. Synthetic demo requires explicit opt-in (`VII_DEMO_MODE=true` or `demo=true`); hashing, ffprobe, dataset CSV, persistence, and report export remain local without a provider.

## 2. Core stack (implemented)

Verification key: "grep-verified" = import/configuration found by the searches run this session. Test, lint, and migration execution is **NOT EXECUTED** this session unless stated otherwise (the 2026-11-02 audit attempts were held by the execution classifier, so nothing was run).

| Layer | Technology (minimum from `pyproject.toml`) | Responsibility in VII | Where used (file paths) | Verification status |
|---|---|---|---|---|
| Runtime | Python ≥3.12 (`requires-python`, pyproject:9) | Language runtime | `pyproject.toml:9`; `target-version = "py312"` (pyproject:43) | Config grep-verified; interpreter run NOT EXECUTED |
| API | FastAPI ≥0.110 | HTTP routing, OpenAPI, DI | `src/vii/api/app.py:13`, `src/vii/api/v1.py:22`, `src/vii/api/routes.py:11` | Grep-verified; API tests NOT EXECUTED |
| API server | uvicorn ≥0.29 | ASGI server | `src/vii/api/app.py:82-83` (lazy import in `run()`) | Grep-verified; server start NOT EXECUTED |
| Contracts | Pydantic ≥2.0 | Domain/request schemas | `src/vii/domain/schemas.py`; `Field` in `src/vii/config.py:9` | Grep-verified; tests NOT EXECUTED |
| Settings | pydantic-settings ≥2.0 | Env-driven `Settings` (`.env` via `env_file`, config.py:38) | `src/vii/config.py:10,37-38` | Grep-verified; startup NOT EXECUTED |
| Persistence | SQLAlchemy ≥2.0 | ORM models, engines, sessions | `src/vii/persistence/models.py:6-7`, `src/vii/persistence/db.py:6-7`, `src/vii/persistence/repositories.py:8` | Grep-verified; tests NOT EXECUTED |
| Migrations | Alembic ≥1.13 | Schema revisions | `alembic/env.py:3`, `alembic/versions/0001_initial.py:14` | Grep-verified; `alembic upgrade/downgrade` NOT EXECUTED |
| Default DB | SQLite (stdlib driver via SQLAlchemy) | Zero-config local database | Default `VII_DATABASE_URL=sqlite:///./data/vii.db` (`src/vii/config.py:51`) | Grep-verified; migration/run NOT EXECUTED |
| DB portability | PostgreSQL compatibility (models only) | Portable column types, same models | `src/vii/persistence/models.py:1` docstring; `alembic/versions/0001_initial.py:8` | **Compatibility only — no PostgreSQL driver (`psycopg`) is declared in `pyproject.toml`; deployment NOT EXECUTED (see §9)** |
| HTTP client | HTTPX ≥0.27 | Provider ping and platform APIs | `src/vii/providers/meta.py:16`, `src/vii/platforms/instagram.py:13`, `src/vii/platforms/facebook.py:12` | Grep-verified; **runtime dependency only** (`pyproject.toml:18`; redundant dev-extra duplicate removed in this audit) |
| Provider SDK | OpenAI SDK ≥1.30 (transport only) | Meta Responses-API calls inside the adapter | `src/vii/meta/client.py:52-54` (`from openai import OpenAI`, lazy) | Grep-verified; live calls NOT EXECUTED, no credits spent |
| Uploads | python-multipart ≥0.0.18 | Multipart parsing for `UploadFile` endpoints | Declared `pyproject.toml:19`; consumed via FastAPI in `src/vii/api/v1.py:22` | Grep-verified; upload tests NOT EXECUTED |
| Media tools | FFmpeg / ffprobe (external binaries, not pip) | Probe, extract, convert, sample frames | `src/vii/media/ffmpeg.py:1,22-23` (subprocess, no shell); bins configured at `src/vii/config.py:55-56` | Grep-verified; media execution NOT EXECUTED |
| Image hashing | Pillow ≥10.0, ImageHash ≥4.3 | Perceptual hashes for originality | `src/vii/media/hashing.py:19-20,35-36` (lazy imports, graceful fallback at :17) | Grep-verified; tests NOT EXECUTED |
| Secrets storage | keyring ≥24 (desktop extra only) | OS credential store for the API key | `src/vii/keystore.py:23,49` (lazy `import keyring`); used by `src/vii/config.py:116,127` | Grep-verified — **keyring is used** (see §9); without the extra, `vii.keystore` falls back to a 0600 file |
| Tests | pytest ≥8.0, pytest-asyncio ≥0.23 (dev extra) | Unit/integration/API tests | `pyproject.toml:27,37-39` (`testpaths`, `asyncio_mode = "auto"`); `tests/` | Config grep-verified; **test run NOT EXECUTED this session** |
| Lint | Ruff ≥0.5 (dev extra) | Lint | `pyproject.toml:41-47` (`[tool.ruff]`, select E/F/I/UP/B) | Config grep-verified; **`ruff check` NOT EXECUTED this session** |
| Desktop UI (optional) | PySide6 ≥6.7 (desktop extra) | Optional Qt desktop app | `src/vii/ui/main_window.py:6-7`, `src/vii/ui/workers.py:4`, `src/vii/ui/views/*.py` | Grep-verified; UI NOT EXECUTED |

## 3. Layer-by-layer detail

### API layer — `src/vii/api/` (FastAPI)
Versioned `/v1` router is the consumer contract; unversioned routes in `routes.py` are deprecated and share the v1 consumer identity. Non-obvious decision: `/health` (liveness) is separate from `/ready` (DB + storage readiness), and responses carry `X-Request-Id`. Risk: legacy routes must be removed in a future breaking change, not silently kept forever.

### Domain contracts — `src/vii/domain/` (Pydantic)
Pure schemas and enums; no HTTP, SQL, or Qt imports. Non-obvious decision: `supported`/`contradicted` assessments require evidence by validation, and the five report dimensions are never collapsed into one score. Risk: schema drift from provider payloads is contained here, so changes must be deliberate.

### Persistence and migrations — `src/vii/persistence/`, `alembic/` (SQLAlchemy 2, Alembic)
All DB access goes through `repositories.py`; handlers and pipeline code never build queries. Non-obvious decision: `create_all` remains only as the zero-config dev fallback, while `alembic/versions/0001_initial.py` is the reproducible path. Risk: model/migration drift is possible — the migration was written by hand and its execution is NOT EXECUTED.

### Provider adapter (Meta) — `src/vii/meta/`, `src/vii/providers/` (OpenAI SDK transport, HTTPX)
`MetaClient` (`src/vii/meta/client.py:29-32`) isolates request construction, auth, parsing, retries (`max_retries=2`), and timeouts (`timeout_s=120.0`); it defaults to model `muse-spark-1.3` and transcription model `muse-voice-transcribe-1.0`. Non-obvious decision: vendor specifics never leak past this adapter. Risk: **live protocol compatibility is unverified** — no credentials were available and no live call was executed; mocks are the only evidence.

### Media pipeline — `src/vii/media/` (FFmpeg/ffprobe, Pillow/ImageHash)
Ingestion classifies URLs, applies an SSRF guard, and probes/converts via subprocess with `shell=False` and timeouts (`src/vii/media/ffmpeg.py`). Non-obvious decision: originals are preserved; derivatives get separate hashes. Risk: social page URLs are never media input — only authorized platform APIs or local uploads work.

### Evidence and verification — `src/vii/evidence/`, `src/vii/verification/`
Retrieval returns cited sources; assessment assigns per-claim status from evidence. Non-obvious decision: without a live client no search is performed and results are empty (`performed=False`) — in the default online path a missing key fails the job before this point, so no fake evidence is ever fabricated. Risk: live evidence quality depends entirely on the provider's web search, which is unverified here.

### Integrity — `src/vii/integrity/` (SHA-256, perceptual hashing)
Provenance and originality use exact + perceptual hashes (`src/vii/media/hashing.py`), never a fabricated AI-detector verdict. Non-obvious decision: originality compares against a local corpus under `storage_dir/corpus` (`src/vii/application/pipeline.py:224`). Risk: an empty corpus means "no match found", not "original" — reports must keep that distinction.

### Dataset CSV subsystem — `src/vii/dataset/` (stdlib `csv`)
`validate_csv`/`ingest_csv` (`src/vii/dataset/ingestion.py:107,237`) implement the canonical `data/dataset.csv` contract: required `video_id` column, per-row errors with line numbers, duplicate detection, dry-run-by-default idempotent ingestion. Non-obvious decision: a missing file is a normal state, and ingestion never starts analysis. Risk: real-world CSV dialects/encodings beyond the sniffed set will surface as row errors, by design.

### Reports — `src/vii/reports/` (JSON + Markdown export)
`exporter.py:8,40` keeps five dimensions separate (`DIMENSIONS`) and writes JSON/Markdown under `storage_dir/exports` (`src/vii/application/pipeline.py:446`). Non-obvious decision: a succeeded job re-run returns the persisted report instead of recomputing. Risk: report files on disk and `reports.payload_json` must stay consistent; reads are consumer-checked.

### Application / worker — `src/vii/application/` (ThreadPoolExecutor, DB-backed queue)
`Worker` (`src/vii/application/worker.py:22`) uses a thread pool with the job status column and `processing_logs` as the durable record; bounded retries (`max_retries=2`, worker.py:25) and restart recovery (worker.py:156). Non-obvious decision: no broker — durability comes from the database, and recovery re-enqueues with `force=True` only from `recover()`. Risk: single-process only; multi-host workers would need a real queue (see §8).

### Optional desktop UI — `src/vii/ui/` (PySide6)
Qt views over the same application services; secrets go to the OS keyring, never `.env` (`src/vii/ui/views/settings.py:70`). Non-obvious decision: the UI is an extra, never required for API/headless use. Risk: UI code paths are the least exercised; nothing in the UI was executed this session.

### Online-first and explicit demo mode
`demo = job's stored demo flag or settings.demo_enabled` (`src/vii/application/pipeline.py`); `demo_enabled` requires an explicit `VII_DEMO_MODE=true` (or deprecated `VII_OFFLINE_MODE=true` alias, or per-request `demo=true`). Otherwise a missing key raises `ProviderConfigurationError` at job creation/run and the job is marked `failed`. Demo understanding/transcription use `DEMO_*` fixtures labeled **SYNTHETIC DEMO** in reports. Self-contained local functionality: API + auth, SQLite persistence, dataset CSV validation/ingestion, hashing, ffprobe metadata, and report export from persisted data. Video understanding, transcription, and evidence search require the external provider.

## 4. Configuration and environment

Generated from `src/vii/config.py` and compared with `.env.example`. The two files list **exactly the same 32 variables** — no variable exists in one but not the other.

| Env var | Type | Default | Required? | Purpose |
|---|---|---|---|---|
| `MODEL_API_KEY` | str | `""` | Only for live mode | Meta API key (or OS keyring via `vii.keystore`) |
| `META_BASE_URL` | str | `https://api.meta.ai/v1` | No | Provider endpoint |
| `META_MODEL` | str | `muse-spark-1.3` | No | Understanding model |
| `META_TRANSCRIPTION_MODEL` | str | `muse-voice-transcribe-1.0` | No | Transcription model |
| `VII_DEMO_MODE` | bool | `false` | No | Explicit synthetic-demo opt-in (never a fallback) |
| `VII_OFFLINE_MODE` | bool | `false` | No | Deprecated alias of `VII_DEMO_MODE` |
| `VII_DATABASE_URL` | str | `sqlite:///./data/vii.db` | No | SQLAlchemy URL |
| `VII_STORAGE_DIR` | Path | `./data` | No | Storage root (see §5) |
| `VII_MAX_UPLOAD_MB` | int | `512` | No | Streaming upload cap |
| `VII_MAX_VIDEO_SECONDS` | int | `3600` | No | Max accepted duration |
| `VII_FFMPEG_BIN` | str | `ffmpeg` | No | FFmpeg binary |
| `VII_FFPROBE_BIN` | str | `ffprobe` | No | ffprobe binary |
| `VII_SEARCH_CONTEXT_SIZE` | str | `medium` | No | Provider search context size |
| `VII_ENABLE_TRANSCRIPTION` | bool | `true` | No | Gate the separate audio-extraction + transcription stage |
| `VII_ENABLE_VISUAL_PERCEPTION` | bool | `false` | No | Gate the optional visual-perception stage (`local` and `sam` implemented, see §9) |
| `VII_VISUAL_PERCEPTION_PROVIDER` | str | `""` | No | Provider: `local` (implemented, `available_local`) or `sam` (SAM 3.1 adapter, `configured_unverified` with a key) |
| `VII_SAM_API_KEY` | str | `""` | No | SAM credential override (redacted in diagnostics; falls back to `MODEL_API_KEY` — the docs-verified SAM contract uses the same Bearer key) |
| `VII_SAM_MODEL` | str | `""` | No | SAM model identifier override; empty = the docs-verified default `sam-3.1` |
| `VII_API_HOST` | str | `127.0.0.1` | No | Bind host (loopback enforced without auth) |
| `VII_API_PORT` | int | `8765` | No | Bind port |
| `VII_INSTAGRAM_TOKEN` | str | `""` | No | Authorized Instagram API access |
| `VII_FACEBOOK_PAGE_TOKEN` | str | `""` | No | Authorized Facebook Page API access |
| `VII_API_KEYS` | str (comma list) | `""` | With `VII_REQUIRE_AUTH=true` (or `VII_CONSUMER_KEYS`) | Bare service keys; identity = `key-<SHA-256>` |
| `VII_CONSUMER_KEYS` | str (`name:key,...`) | `""` | With `VII_REQUIRE_AUTH=true` (or `VII_API_KEYS`) | Named consumer key mapping |
| `VII_CONSUMER_ID` | str | `default` | No | Identity when auth is disabled |
| `VII_STORAGE_BACKEND` | str | `local` | No | `local` or `s3` (see §5/§7) |
| `VII_S3_BUCKET` | str | `""` | For `s3` backend | S3 bucket |
| `VII_S3_ENDPOINT` | str | `""` | No | S3-compatible endpoint |
| `VII_WORKER_CONCURRENCY` | int | `2` | No | Worker thread pool size |
| `VII_REQUIRE_AUTH` | bool | `false` | Required `true` for non-loopback binds | Enforce Bearer service keys |
| `VII_WEBHOOK_ENABLED` | bool | `false` | No | Arm webhook delivery (SSRF-validated, `src/vii/api/v1.py:101-108,393+`) |
| `DATASET_CSV_PATH` | Path | `data/dataset.csv` | No | Dataset CSV location; absent file is normal |

Internal, not env-exposed: `request_timeout_s: float = 120.0` and `max_retries: int = 2` (`src/vii/config.py:75-76`), passed into the provider adapter. `Settings` also fails closed at startup: `VII_REQUIRE_AUTH=true` without keys, or a non-loopback bind without auth, raises (`src/vii/config.py:88-104`).

## 5. Data and storage

- **SQLite vs PostgreSQL.** SQLite is the implemented default (`VII_DATABASE_URL`). The 12 models use portable SQLAlchemy types, but **no PostgreSQL driver is declared**, so PostgreSQL is a compatibility property of the models, not a verified deployment (see §9).
- **The 12 tables** (`src/vii/persistence/models.py`, verified by grep): `analysis_jobs`, `video_sources`, `meta_requests`, `claims`, `evidence_sources`, `citations`, `claim_assessments`, `transcript_segments`, `search_sessions`, `processing_logs`, `reports`, `dataset_samples`. Source records, processing runs, evidence, and reports are separate tables by design.
- **Storage directory.** `LocalStorage` creates 11 areas under `VII_STORAGE_DIR` (`src/vii/storage/__init__.py:11-12`): `originals`, `derived`, `tmp`, `frames`, `audio`, `fingerprints`, `reports`, `datasets`, `corpus`, `media`, `exports`.
- **Local vs S3.** Local is the implemented default. `S3Storage` code exists (`src/vii/storage/__init__.py:43-83`) with a lazy `boto3` import — but `boto3` is declared nowhere in `pyproject.toml`, so the S3 backend cannot run on a standard install and is classified in §7, not as selected.

## 6. Security-relevant stack choices

Auth model (fail-closed `Settings` guards, consumer isolation), SSRF guard, streamed upload limits, log/diagnostics redaction, and the loopback rule are summarized from the code in §2/§4 above. The authoritative detail — threat boundaries, webhook validation, dataset path restrictions, media/process safety, and honest known limits — lives in `docs/SECURITY.md` and is not duplicated here.

## 7. Planned / not yet implemented

| Technology | Why it might be needed | Demonstrated need that does not yet exist |
|---|---|---|
| mypy / Pyright (enforced) | Catch contract drift across layers | No checker is configured (no `[tool.mypy]`/pyright config in `pyproject.toml`); Ruff covers the current defect classes. Add when the public contract stabilizes. |
| PostgreSQL deployment (driver, e.g. `psycopg`) | Shared/multi-process deploys | Single-process SQLite is the only executed-path design; no driver is declared and no Postgres instance was tested. |
| S3 storage backend (usable) | Shared object storage | `S3Storage` code exists but `boto3` is undeclared; no bucket, credentials, or test exists. |
| NumPy (direct use) | Numeric media/array work | **Resolved in this audit:** no `import numpy` exists in `src/` or `tests/` (grep-verified), so the direct declaration was removed from `pyproject.toml`; any use is transitive via ImageHash. |
| python-dotenv (direct use) | `.env` loading | **Resolved in this audit:** never imported directly; `pydantic-settings` already loads `.env` (`src/vii/config.py:38`), so the direct declaration was removed from `pyproject.toml`. |
| Message broker / task queue (Redis, Celery, …) | Multi-host workers | Single-process DB-backed worker meets current scale; no multi-host requirement exists. |

## 8. Rejected alternatives

| Alternative | Why not now |
|---|---|
| Microservices | One deployable process keeps transactions, job state, and reports consistent; no independent scaling need is demonstrated. |
| Redis / Celery / Kafka | DB-backed worker provides durable states, bounded retries, and restart recovery at current scale (§3). |
| Vector database | No embedding retrieval exists; evidence comes from provider web search with URL citations. |
| A second ORM / raw SQL layer | All persistence already flows through SQLAlchemy repositories; a second stack would duplicate the boundary. |
| Kubernetes / mandatory Docker | The app is one process + optional DB; local development must work without orchestration. |
| A second HTTP client (`requests`, etc.) | HTTPX + the provider SDK cover all outbound calls; no `requests` import exists. |

## 9. Open discrepancies

1. **Model name.** The reference material says "Meta Muse Wonder API", but the adapter actually defaults to **`muse-spark-1.3`** (`src/vii/config.py:42`, `src/vii/providers/meta.py:44`) with transcription `muse-voice-transcribe-1.0` (`src/vii/meta/client.py:32`); no `muse-wonder` string exists in `src/` or `.env.example` (grep-verified). Which name the live service expects is **unverified — no live call was executed**.
1b. **Visual perception: local provider and SAM 3.1 adapter implemented.** `VII_VISUAL_PERCEPTION_PROVIDER=local` selects `LocalVisualPerceptionProvider` (`src/vii/providers/visual.py`): FFmpeg-sampled frames plus Pillow frame analysis (shot segments, inter-frame change), capability status `available_local`, `supports_tracking=false`, no masks and no prompt-based detections. `sam` selects `SamVisualPerceptionProvider`, implemented against the SAM 3.1 contract verified from Meta's official documentation (supplied 2026-11-03): model `sam-3.1`, `POST /v1/responses` on the Meta Model API base URL, the same Bearer key as the rest of the API (`VII_SAM_API_KEY` may override), one noun-phrase concept per request, native-video/`video_url` or Files-API `file_id` input, and the documented per-frame `<Nf>id<|box|><|mask|>` output grammar with stable tracking ids (mask payloads stored as encoded artifacts, not decoded by VII). Capability status stays `configured_unverified` (a per-configuration state, not a history flag). **Live verified 2026-11-03:** a direct call (concept "flower", public MDN flower MP4) returned 125 segmentation observations and a full pipeline run returned 363 with the job succeeded — see `docs/ARCHITECTURE.md` for the evidence (the planned `gtv-videos-bucket` sample URL now 403s anonymously and was substituted). Video is billed per frame (50-frame minimum per request); demo mode never calls SAM. Without a key, selecting `sam` returns the explicitly **blocked** unavailable provider and never a fabricated result.
1c. **Usage & retries (changed).** `MetaClient` now preserves provider-returned `usage` via `provider_usage()` (absent usage → `unknown`, cost stays unknown while pricing is unverified), classifies 401/403 as terminal `ProviderPermissionError`, and the worker no longer retries whole jobs on configuration/permission/validation failures (which would re-upload and re-spend). Ingestion-only validation (`vii --ingest-only`, `inspect_local_media`) needs no provider, job, or FFmpeg for a supported MP4.
2. **HTTPX classification.** HTTPX is a **runtime** dependency (`pyproject.toml:18`, imported at `src/vii/providers/meta.py:16` and `src/vii/platforms/*.py`). **Resolved in this audit:** the redundant dev-extra duplicate was removed from `pyproject.toml`.
3. **keyring.** There **is** an import — lazy, at `src/vii/keystore.py:23,49`, used via `Settings.effective_api_key`. The desktop extra is therefore justified; the caveat is that API-only installs silently fall back to the 0600 file. **Recommendation: keep the extra** (do not remove).
4. **requirements.txt.** **Resolved (library modernization):** regenerated to mirror the `pyproject.toml` `[app]` extra exactly. It no longer forces dev tools (`pytest`, `ruff`) or the removed `numpy`/`python-dotenv` declarations on every install. Canonical installs remain `pip install -e ".[dev]"` (full app + tests) or `pip install -e .` (core library only).
5. **Unused declarations.** **Resolved in this audit for `pyproject.toml`:** `numpy` and `python-dotenv` were declared but never imported directly (grep-verified; see §7) and were removed. `requirements.txt` has since been regenerated to match (see item 4). Core library dependencies are now only `pydantic`/`pydantic-settings`; FastAPI/uvicorn, SQLAlchemy/Alembic, OpenAI SDK/HTTPX, and Pillow/ImageHash are optional extras (`api`, `db`, `provider`, `media`, combined as `app`; `dev` includes the full stack for tests).
6. **PostgreSQL / S3 gap.** Both are described in code docstrings (`src/vii/persistence/models.py:1`, `src/vii/storage/__init__.py:4-5`) as production targets, but neither a Postgres driver nor `boto3` is declared. Docstrings overstate the installable reality; §5/§7 classify them accordingly.
7. **Verification debt.** Everything in §2 is grep-verified for usage only. `pytest`, `ruff check`, Alembic upgrade/downgrade, server startup, and all live-provider behavior are **NOT EXECUTED** this session (the 2026-11-02 audit attempts were held before execution). No production readiness, model accuracy, or working live integration is claimed.
