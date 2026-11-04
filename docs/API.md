# API Reference

Base URL (local dev): `http://127.0.0.1:8765`. Interactive OpenAPI: `/docs`.
The consumer contract is the versioned `/v1` router. Unversioned legacy
routes are deprecated, kept for local compatibility, and now enforce
the same authentication as `/v1`.

## Conventions

1. Versioning. All new work targets `/v1`. Breaking changes ship under
   a new prefix. `/v1` behavior changes are documented in
   `docs/TECH_STACK.md`.
2. Authentication. When `VII_REQUIRE_AUTH=true`, send
   `Authorization: Bearer <service key>`. Identity resolution: the
   `VII_CONSUMER_KEYS` mapping (`name:key`) gives the operator assigned
   consumer name. Otherwise the consumer id is `key-<full SHA 256 of
   the key>` (stable, never the raw key). When auth is disabled
   (loopback only dev), identity is the `X-Consumer` header or
   `VII_CONSUMER_ID` (default `default`).
3. Isolation. Every job, dataset, and report read is scoped to the
   calling consumer. Cross consumer access returns `404`, never
   another consumer data.
4. Errors. FastAPI JSON errors look like `{"detail": "..."}` with
   `400` (invalid input), `401` (missing key), `403` (invalid key),
   `404` (unknown or foreign owned resource), `409` (prerequisite
   missing, for example no report yet), `413` (upload too large),
   `500` (execution or enqueue failure).
5. Correlation. Responses carry `X-Request-Id` (echoed if supplied,
   else a generated `req_<hex>` value). The same id is on
   `request.state.request_id`.
6. Idempotency. Re posting an analysis creates a new job (job creation
   is not idempotent by design). Enqueueing or running an already
   running, terminal, or succeeded job is a no op (succeeded runs
   return the persisted report).
7. Long running work. `POST /v1/analyses` enqueues and returns
   immediately; poll `GET /v1/jobs/{id}`. The path
   `POST /v1/analyses/{id}/run` is the synchronous path for small jobs.

## Health

1. `GET /health` and `GET /v1/health` (no auth): liveness plus mode
   (`live_mode`, `offline_mode`, model).
2. `GET /ready` (no auth): readiness with DB `SELECT 1` plus storage
   dir check; `503` when unready.
3. `GET /diagnostics` and `GET /v1/diagnostics` (auth on v1): redacted
   settings plus ffmpeg and ffprobe presence plus `capabilities` per
   capability states. Secrets never returned. No provider is contacted.

## Ingestion only validation (no analysis)

`python3 -m vii.main --ingest-only PATH` validates and hashes one
local media file (existence, readability, size, container signature,
SHA 256, MP4 duration when locally determinable) and prints a JSON
`MediaIngestionResult`. It creates no analysis job, enqueues no
worker, and calls no provider. Supported native MP4 ingestion does not
require FFmpeg. Exit `0` means valid, `2` means rejected (typed error
in the JSON body). There is deliberately no HTTP route for arbitrary
server paths. HTTP ingestion remains `POST /v1/uploads` followed by
`POST /v1/analyses`.

## Analyses and jobs (/v1)

1. `POST /v1/analyses`: create plus enqueue. Body:
   `AnalysisCreate {source:{kind,url?,local_path?}, title?, demo?,
   tasks?[]}` (`demo=true` is the explicit synthetic demo opt in;
   `offline` is its deprecated alias). Returns
   `201 {job_id, status:"queued", webhook}`. Optional `?webhook_url=`
   (delivery disabled unless `VII_WEBHOOK_ENABLED=true`; SSRF
   validated, signed).
2. `POST /v1/analyses/{job_id}/run`: synchronous run (small jobs).
   Provider or configuration failures mark the job `failed` and return
   a typed error, never demo output.
3. `GET /v1/jobs/{job_id}` and `GET /v1/analyses/{job_id}`: job
   detail with status, claims plus assessments, evidence, citations,
   transcript, and processing log.
4. `POST /v1/jobs/{job_id}/cancel`: cooperative cancellation.
5. `GET /v1/analyses/{job_id}/report`: JSON report (`404` until
   succeeded).
6. `GET /v1/analyses/{job_id}/report.md`: Markdown report.
7. `POST /v1/uploads`: multipart video upload (streamed,
   `VII_MAX_UPLOAD_MB` enforced). Returns `{storage_ref, sha256,
   size_mb}` for use in an analysis.

## Investigation and comparison (/v1)

1. `POST /v1/search/investigate`: per query evidence investigation
   (`{query, claim_id?, context_size?}`). Live mode uses Meta web
   search. Without a live provider, `performed` is `false` with an
   explicit no search note.
2. `POST /v1/content/compare`: reused asset comparison. Exact SHA 256
   pair gives a match verdict; two completed job ids give a report
   backed SHA and pHash comparison.

## Datasets (/v1)

1. `POST /v1/datasets/samples`: register one video in the caller inbox.
   `local_path` must resolve under `VII_STORAGE_DIR` (use
   `/v1/uploads` first).
2. `GET /v1/datasets/search?q=&limit=`: substring search over video id,
   URL, and platform, plus exact sha256.
3. `GET /v1/datasets/samples/{sample_id}`: one inbox sample,
   consumer scoped.
4. `GET /v1/datasets/check`: validate configured CSV
   (`DATASET_CSV_PATH`, default `data/dataset.csv`). Read only. A
   missing file gives `200 {exists:false}`.
5. `POST /v1/datasets/ingest-csv?dry_run=true`: validate plus
   preview; `dry_run=false` registers rows idempotently. Never starts
   analysis.

See `docs/DATASET.md` for the CSV schema.

## Legacy routes (deprecated)

`GET /health`, `GET /diagnostics`, `POST /analyses`,
`POST /analyses/{id}/run`, `GET /analyses`, `GET /analyses/{id}`,
`GET /analyses/{id}/report`. Same handlers now require the v1
consumer identity. With `VII_REQUIRE_AUTH=true` they reject
missing or invalid keys exactly like `/v1`. Migrate to `/v1`.
Legacy routes may be removed in a future major version.
