# VII Architecture

Video Integrity Intelligence (VII) is an API-first, evidence-first engine for
investigating video integrity, factual claims, and supporting evidence. It is a
**modular monolith**: one deployable Python process (plus an optional desktop
UI) with explicit internal boundaries — no microservices, message broker, or
vector store is required for the current workload.

## System context

```
Operators / API consumers
        │  HTTP (Bearer service key when VII_REQUIRE_AUTH=true)
        ▼
┌────────────────────────── VII process ──────────────────────────┐
│  FastAPI app (vii.api.app)                                       │
│    ├─ /v1  consumer contract (vii.api.v1)                        │
│    └─ /*   legacy unversioned routes (deprecated, same auth)     │
│  AnalysisService (vii.application.services) ── Pipeline           │
│    ├─ Ingestion → Video understanding → Transcription            │
│    ├─ Claim extraction → Evidence search → Assessment            │
│    └─ Origin / Originality → JSON+Markdown reports               │
│  Worker (vii.application.worker) — DB-backed ThreadPool          │
│  Persistence (vii.persistence) — SQLAlchemy 2.x + Alembic        │
│  Dataset (vii.dataset) — CSV validation + inbox ingestion        │
└──────────────────────────────────────────────────────────────────┘
        │                         │
        ▼                         ▼
  Meta Model API            FFmpeg / ffprobe
  (vii.meta adapter)        (vii.media, subprocess, no shell)
```

## Layers and dependency direction

Dependencies point **inward and downward**; lower layers never import the API
or UI.

| Layer | Package | Responsibility | May import |
|---|---|---|---|
| Transport | `vii.api` | HTTP routing, auth dependency, status codes | application, config, domain, errors |
| Application | `vii.application` | Use cases: pipeline orchestration, service facade, worker lifecycle | domain, persistence, media, meta, evidence, verification, integrity, reports, dataset |
| Domain | `vii.domain` | Pydantic contracts + enums. No Qt, SQL, or HTTP imports. | stdlib, pydantic only |
| Persistence | `vii.persistence` | ORM models, engine/session, repositories (all DB access) | domain (enums only) |
| Providers | `vii.meta`, `vii.providers` | Model-API transport, payloads, response parsing; legacy Provider protocol + mocks | domain, config, errors |
| Evidence | `vii.evidence` | Retrieval orchestration, source ranking, citation validation | domain, meta |
| Verification | `vii.verification` | Claim classification + evidence-grounded assessment rules | domain, evidence |
| Media | `vii.media` | Ingestion validation, SSRF guard, ffmpeg/ffprobe, hashing | domain |
| Integrity | `vii.integrity` | Media-origin notes, originality (SHA-256 + pHash) | domain, media |
| Reports | `vii.reports` | JSON/Markdown payload building and export | stdlib only |
| Dataset | `vii.dataset` | CSV schema validation, row errors, idempotent inbox ingestion | persistence (lazy) |
| Platform | `vii.platforms`, `vii.media.social` | Authorized Instagram/Facebook API retrieval, URL classification | media |
| Storage | `vii.storage` | Local filesystem layout; optional S3-compatible backend | stdlib (+ lazy boto3) |
| UI | `vii.ui` | PySide6 desktop views (optional extra) | application, config |

**Rules**

- All database access goes through `vii.persistence.repositories`. API handlers
  never write ORM queries directly (dataset CSV endpoints delegate to
  `vii.dataset.ingestion`).
- External providers are replaceable: pipeline code depends on
  `MetaClient`-shaped interfaces and Pydantic domain types, never on raw vendor
  JSON outside `vii.meta.response_parser`.
- Optional subsystems stay optional: no PySide6, keyring, or boto3 is required
  to start the API; a live API key is required only for provider-backed
  analysis (local operations — dataset CSV, hashing, ffprobe, persistence,
  report export — run without one).

## Data flow (one analysis)

1. `POST /v1/analyses` → `AnalysisService.create` → `Pipeline.create_job`
   persists an `analysis_jobs` row (`queued`, consumer-scoped) → `Worker.enqueue`.
2. Worker executes `Pipeline.run` through stages, persisting status to
   `analysis_jobs.status` and audit lines to `processing_logs` at each step:
   ingestion (SSRF-guarded URL validation or local-file checks, optional MP4
   conversion) → native video understanding (URL `input_video` or Files-API
   `file_id`) → transcription → claim extraction (factual vs opinion/satire/
   prediction) → per-claim web search + citation capture → rule-based
   assessment → origin/originality → report export (DB `reports` rows + files
   under `storage_dir/exports/`).
3. Clients poll `GET /v1/jobs/{id}`; reports via `GET /v1/analyses/{id}/report(.md)`.
4. Online-first: without a key the job fails with `ProviderConfigurationError`
   (status `failed`, reason persisted). Synthetic demo fixtures run only on
   explicit opt-in (`VII_DEMO_MODE=true` / `demo=true`) and are labeled
   SYNTHETIC DEMO — never presented as live evidence.

Job states: `queued → ingesting → understanding_video → transcribing →
extracting_claims → searching → assessing → reporting → succeeded`, with
`failed` / `cancelled` terminals. Claim IDs are job-scoped
(`<job_id>_c001`), assessments require evidence for supported/contradicted.

## Background processing

`vii.application.worker.Worker` is a bounded `ThreadPoolExecutor` whose queue
of record is the database itself (status column + `processing_logs`). It
provides: idempotent enqueue (running/terminal jobs are not re-executed),
bounded retries with persisted failure logs, cooperative cancellation, and
restart recovery (`recover()` force re-enqueues stale `queued`/running jobs).
This is sufficient for a single-process deployment; a persistent external queue
(Redis/Celery) is only justified by multi-process scale-out — see
`docs/TECH_STACK.md`.

## Dataset flow

`data/dataset.csv` (or `DATASET_CSV_PATH`) → `vii.dataset.ingestion.validate_csv`
(schema + row errors, no side effects) → explicit ingest (`--apply` or
`POST /v1/datasets/ingest-csv?dry_run=false`) → `DatasetRepo` inbox rows
(`annotation_status='pending'`). Ingestion never creates analyses, downloads
media, or calls a model. See `docs/DATASET.md`.

## Architectural decisions

- **AD-1 Modular monolith over microservices.** One process keeps transactions,
  job state, and reports consistent with the least operational cost.
- **AD-2 Database-as-queue over Celery/Redis.** Job volume is interactive and
  single-process today; the DB status machine gives durability and recovery
  without new infrastructure. Revisit if workers must span hosts.
- **AD-3 Five separate assessment dimensions, never one real/fake score.**
  Claim verification, evidence, media origin, originality, and limitations are
  reported independently (`vii.reports.exporter.DIMENSIONS`).
- **AD-4 Provider adapter over vendor coupling.** `vii.meta` owns all Meta
  request construction/parsing/retries; `vii.providers` preserves the legacy
  Protocol + an explicitly-opted-in synthetic mock for tests.
- **AD-5 Online-first honesty.** Missing keys, provider failures, missing
  datasets, and missing media binaries produce explicit typed errors or
  labeled unavailable states, never fabricated results.
