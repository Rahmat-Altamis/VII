# API Reference

Base URL (local dev): `http://127.0.0.1:8765`. Interactive OpenAPI: `/docs`.
The consumer contract is the **versioned `/v1` router**; unversioned legacy
routes (`/*`) are deprecated, kept for local compatibility, and now enforce
the same authentication as `/v1`.

## Conventions

- **Versioning.** All new work targets `/v1`. Breaking changes ship under a
  new prefix; `/v1` behavior changes are documented in
  `docs/TECH_STACK.md` §9.
- **Authentication.** When `VII_REQUIRE_AUTH=true`, send
  `Authorization: Bearer <service-key>`. Identity resolution:
  `VII_CONSUMER_KEYS` mapping (`name:key`) → operator-assigned consumer name;
  otherwise the consumer id is `key-<full SHA-256 of the key>` (stable,
  never the raw key). When auth is disabled (loopback-only dev), identity is
  the `X-Consumer` header or `VII_CONSUMER_ID` (default `default`).
- **Isolation.** Every job/dataset/report read is scoped to the calling
  consumer. Cross-consumer access returns `404`, never another consumer's data.
- **Errors.** FastAPI JSON errors: `{"detail": "..."}` with `400` (invalid
  input), `401` (missing key), `403` (invalid key), `404` (unknown or
  foreign-owned resource), `409` (prerequisite missing, e.g. no report yet),
  `413` (upload too large), `500` (execution/enqueue failure).
- **Correlation.** Responses carry `X-Request-Id` (echoed if supplied,
  else generated `req_<hex>`); the same id is on `request.state.request_id`.
- **Idempotency.** Re-POSTing an analysis creates a new job (job creation is
  not idempotent by design); enqueueing/running an already running, terminal,
  or succeeded job is a no-op (succeeded runs return the persisted report).
- **Long-running work.** `POST /v1/analyses` enqueues and returns
  immediately; poll `GET /v1/jobs/{id}`. `POST /v1/analyses/{id}/run` is the
  synchronous path for small jobs.

## Health

| Endpoint | Auth | Meaning |
|---|---|---|
| `GET /health`, `GET /v1/health` | No | Liveness + mode (`live_mode`, `offline_mode`, model). |
| `GET /ready` | No | Readiness: DB `SELECT 1` + storage dir check; `503` when unready. |
| `GET /diagnostics`, `GET /v1/diagnostics` | Yes (v1) | Redacted settings + ffmpeg/ffprobe presence. Secrets never returned. |

## Analyses & jobs (`/v1`)

| Method & path | Purpose |
|---|---|
| `POST /v1/analyses` | Create + enqueue. Body: `AnalysisCreate {source:{kind,url?,local_path?}, title?, demo?, tasks?[]}` (`demo=true` is the explicit synthetic-demo opt-in; `offline` is its deprecated alias). `201 {job_id, status:"queued", webhook}`. Optional `?webhook_url=` (delivery disabled unless `VII_WEBHOOK_ENABLED=true`; SSRF-validated, signed). |
| `POST /v1/analyses/{job_id}/run` | Synchronous run (small jobs). Provider/configuration failures mark the job `failed` and return a typed error — never demo output. |
| `GET /v1/jobs/{job_id}` · `GET /v1/analyses/{job_id}` | Job detail: status, claims+assessments, evidence, citations, transcript, processing log. |
| `POST /v1/jobs/{job_id}/cancel` | Cooperative cancellation. |
| `GET /v1/analyses/{job_id}/report` | JSON report (`404` until succeeded). |
| `GET /v1/analyses/{job_id}/report.md` | Markdown report. |
| `POST /v1/uploads` | Multipart video upload (streamed, `VII_MAX_UPLOAD_MB` enforced). Returns `{storage_ref, sha256, size_mb}` for use in an analysis. |

## Investigation & comparison (`/v1`)

| Method & path | Purpose |
|---|---|
| `POST /v1/search/investigate` | Per-query evidence investigation (`{query, claim_id?, context_size?}`). Live mode uses Meta web search; without a live provider, `performed` is `false` with an explicit no-search note. |
| `POST /v1/content/compare` | Reused-asset comparison. Exact SHA-256 pair → match verdict; two completed job ids → report-backed SHA/pHash comparison. |

## Datasets (`/v1`)

| Method & path | Purpose |
|---|---|
| `POST /v1/datasets/samples` | Register one video in the caller's inbox. `local_path` must resolve under `VII_STORAGE_DIR` (use `/v1/uploads` first). |
| `GET /v1/datasets/search?q=&limit=` | Substring search (video_id/URL/platform) + exact sha256. |
| `GET /v1/datasets/samples/{sample_id}` | One inbox sample (consumer-scoped). |
| `GET /v1/datasets/check` | Validate configured CSV (`DATASET_CSV_PATH`, default `data/dataset.csv`). Read-only; missing file → `200 {exists:false}`. |
| `POST /v1/datasets/ingest-csv?dry_run=true` | Validate + preview; `dry_run=false` registers rows idempotently. Never starts analysis. |

See `docs/DATASET.md` for the CSV schema.

## Legacy routes (deprecated)

`GET /health`, `GET /diagnostics`, `POST /analyses`,
`POST /analyses/{id}/run`, `GET /analyses`, `GET /analyses/{id}`,
`GET /analyses/{id}/report`. Same handlers now require the v1 consumer
identity — with `VII_REQUIRE_AUTH=true` they reject missing/invalid keys
exactly like `/v1`. Migrate to `/v1`; legacy routes may be removed in a
future major version.
