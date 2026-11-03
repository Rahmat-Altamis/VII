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

## Downstream integration contract

Downstream applications and a future CLI consume the library only
through the public API exported from `vii` (`vii.__all__`): the `VII`
client (`vii.client`), typed input/output models (`AnalysisCreate`,
`VideoSourceIn`, `MediaIngestionResult`, `OriginalityResult`,
`ReportPayload`), `Settings`, and the typed errors in `vii.errors`.
Local client operations (`inspect_media`, `sha256`,
`assess_originality`, `validate_dataset`, `capabilities`) need no
server, database, worker, network, or provider credentials. The only
provider-backed operation, `VII.analyze`, is explicit, runs only when
called, reuses the application pipeline below, and raises
`ProviderConfigurationError` before creating any job when no key is
configured. Internal packages (`vii.api`, `vii.application`,
`vii.persistence`, `vii.meta`, ...) are implementation details;
consumers must not import them.

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

## Ingestion-only operation (no job, no provider)

`python3 -m vii.main --ingest-only PATH` (service:
`vii.media.ingestion.inspect_local_media`) validates one local file —
existence, readability, size limit, container **signature** vs extension
(magic bytes, `vii.media.ingestion.sniff_container`), SHA-256, and duration
from the pure-Python MP4 parser (`vii.media.mp4_probe`, `mvhd`) with
optional ffprobe enrichment when a binary is supplied and installed. It
opens no database, creates no job, enqueues no worker, and imports no
provider module; unsupported/oversized/mismatched media raise typed
`ValueError` subclasses from `vii.errors`. A duration that cannot be
determined locally is reported as unknown — never guessed.

## Provider contracts — verification status

| Capability | Implemented in repo | Contract status |
|---|---|---|
| Muse video understanding (`vii.meta`) | `input_video`/`video_url` + Files-API `file_id` payloads, typed errors, provider-reported `usage` preserved (`provider_usage`) | **Configured-unverified.** The configured identifier is `muse-spark-1.3` (`META_MODEL`); the name “Muse Wonder”, live acceptance of these payloads, format/size/duration limits, Files-API lifecycle, and pricing are **not verified** against official documentation in this environment. No live call has been made. |
| Transcription (`muse-voice-transcribe-1.0`) | FFmpeg extraction + adapter, gated by `VII_ENABLE_TRANSCRIPTION` | Configured-unverified; runs only when enabled **and** a local file exists, so audio extraction is never an unconditional prerequisite. |
| Evidence search | Meta `web_search` retrieval with persisted citations, separate from visual interpretation | Configured-unverified live; without a live provider, `performed=false` and no sources are fabricated. |
| Visual perception (`local` / SAM 3.1) | `VisualObservation`, `VisualPerceptionProvider` protocol, `StageName.VISUAL_PERCEPTION`, optional pipeline stage; `LocalVisualPerceptionProvider` for `VII_VISUAL_PERCEPTION_PROVIDER=local`, `SamVisualPerceptionProvider` for `sam` | **Local implemented; SAM 3.1 adapter implemented, live verified 2026-11-03.** Local: FFmpeg-sampled frames + Pillow analysis (shot segments, inter-frame change), status `available_local`, `supports_tracking=false`, no masks/prompts. SAM 3.1: docs-verified contract (model `sam-3.1`, `POST /v1/responses`, same Bearer key, concept prompts from video-understanding entities, Files-API upload for local files, documented box/mask wire grammar with stable tracking ids; mask payloads stored as encoded artifacts), status `configured_unverified` with a key, `blocked` without one, never called in demo mode. Video is billed per frame (50-frame minimum). Sparse local frames are never described as continuous tracking. Live evidence (2026-11-03): direct call (concept "flower", public MDN flower MP4 via `video_url`) returned 125 segmentation observations (response model `sam-3.1`; frame 25, track id 0, box x1=397,y1=194,x2=561,y2=347, confidence 0.706, one_bit masks under `data/visual_masks/`); full pipeline run on the same URL succeeded (job `job_9413c0ee47ff`) with 363 segmentation observations in `metadata.visual_perception` and exactly five report dimensions. The originally planned `gtv-videos-bucket` sample now returns GCS `AccessDenied` (403) to anonymous fetchers (including the provider's downloader), so the MDN sample was substituted. |
| FFmpeg/ffprobe | Probe/convert/extract/sample utilities (subprocess, no shell) | Optional: required only for non-MP4 conversion, enabled transcription, and frame sampling. Native MP4 ingestion validates without it. |

Provider selection is explicit (`vii.providers.capabilities.provider_capabilities`,
surfaced via diagnostics): states are `configured_unverified`, `blocked`,
`disabled`, `unavailable_no_provider`, or `available_local` (working local
visual provider) — never an implied success.
Whole-job worker retries are limited to typed-retryable or unknown
transient failures; configuration/permission/validation failures are
terminal because re-running cannot fix them and would re-spend provider
calls. Costs are reported only from provider-returned usage; while pricing
is unverified, `estimated_cost_usd` stays unknown rather than invented.

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
