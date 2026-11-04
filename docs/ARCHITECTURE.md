# Architecture

VII is a Python service that ingests a video, understands it with a
hosted model, extracts factual claims, searches the web for evidence,
assesses each claim, detects spam and AI origin signals, and stores a
report. Surfaces: an interactive agent TUI, a scriptable CLI, a
Python library, an HTTP API, four MCP agent tools, and a desktop UI.

## Pipeline stages

Every analysis job passes through the same ordered stages
(`src/vii/application/pipeline.py`). Each stage records started,
finished, capability status, and notes in a per job timeline.

1. Ingesting. Validate the local file or uploaded bytes. Compute
   SHA 256. Probe duration, resolution, fps, and codec with ffprobe
   when available. Fail closed on unreadable duration.
2. Understanding video. Upload the file once, then run the hosted
   video understanding call. Returns a prose summary plus atomic
   factual claims. SHA keyed cache avoids rebilling repeats.
3. Perceiving objects. Optional SAM pass over sampled frames. Counts
   are observation counts, never HTTP codes. A timeout degrades to
   partial, never a crash.
4. Transcribing. Extract audio to normalized WAV (mono, 16 bit PCM,
   24 kHz) and call the Meta ASR endpoint. No audio stream means
   `unavailable`, never an empty success.
5. Searching. For each claim, run evidence search with a relevance
   gate and stance classification (support, refute, neutral).
   Fact check debunks override to contradicted.
6. Assessing. Combine stance counts, source credibility, AI origin
   probability, and spam probability into one of four verdicts:
   supported, contradicted, mixed evidence, insufficient evidence.
7. Reporting. Render JSON plus Markdown narratives (claim text,
   evidence found, reality check, key sources, why this verdict)
   and persist the full record.

Fast path: the library, CLI, and API quick screen run only
ingesting plus a local heuristic screen (no provider calls) and
return in seconds. The deep pipeline is opt in per call.

## Component map

1. `src/vii/application/services.py`: AnalysisService facade,
   the one entry point for analysis orchestration.
2. `src/vii/application/pipeline.py`: stage runner with per stage
   timeouts and the capability ledger.
3. `src/vii/application/worker.py`: background worker plus crash
   recovery for queued and running jobs.
4. `src/vii/meta/`: the only vendor boundary. `client.py`
   uploads, responses, and search. `transcription.py` ASR.
5. `src/vii/verification/`: stance classifier, assessment,
   evidence repository helpers.
6. `src/vii/integrity/`: AI origin scoring (`ai_detection.py`)
   plus spam screening (`spam.py`).
7. `src/vii/media/`: ffprobe wrapper, audio extraction,
   URL fetch guard, validators.
8. `src/vii/persistence/`: SQLAlchemy models, repositories (the
   only DB access), Alembic migrations.
9. `src/vii/api/`: FastAPI app plus the `/v1` router.
10. `src/vii/tui.py`, `src/vii/cli.py`, `src/vii/checker.py`:
    terminal surfaces plus the VideoChecker wrapper.
11. `src/vii/client.py`: the `VII` and `VIIAsync` library clients
    plus the `from vii import VII` entry point.
12. `src/vii/mcp_server.py`: stdio MCP server exposing four tools.
13. `src/vii/config.py`, `src/vii/credentials.py`,
    `src/vii/logging_setup.py`: settings, keystore, redaction.

## Data flow (deep check)

Local file or URL bytes enter ingestion. The SHA 256 of the bytes
keys the understanding cache. The anonymized file id fans out to
video understanding, SAM perception, and ASR transcription. Claims
fan out to one evidence search each. Stances plus credibility feed
assessment. Verdicts plus narratives feed the persisted report.
Failure in one optional capability marks that capability and keeps
every successful sibling result. Nothing synthesizes missing data.

## Failure semantics

1. Required stage fails (ingest, understand): job is `failed`
   with a typed error. No partial report is presented as complete.
2. Optional capability fails (SAM, ASR, one search): capability is
   `failed` or `unavailable`, job continues, report lists the gap.
3. Provider auth fails (401, 403): fail fast, no retry, typed
   `ProviderAuthenticationError`.
4. Provider rate limit (429): bounded backoff, then typed error.
5. Unknown provider payload: typed parse error with redacted body
   excerpt, never a guessed field.

## Caching and cost control

1. Understanding results cache by file SHA 256 in SQLite, so
   rechecking the same bytes never rebills.
2. One upload per file per job. Retries never reupload; they reuse
   the returned file id.
3. Retries never fire on 400, 401, 403, 404, or 413. Transcription
   short circuits on 401 and 403.
4. Demo mode is explicit opt in only and every demo surface is
   labeled SYNTHETIC DEMO.
5. Live provider smoke usage stays inside authorized runs. Routine
   tests use mocked transports exclusively.

## Security boundaries

Vendor credentials live in exactly one layer (`meta/` plus
`credentials.py`). API consumer identity lives in the API layer.
Log redaction applies at the handler level so no emitter can leak
a secret. Path scoping confines every local read. See
`docs/SECURITY.md` for the full model.

## What is intentionally absent

1. No background scheduler. The API worker and the TUI run inline.
2. No multi tenant billing. Consumer scoping isolates data only.
3. No streaming analysis progress over HTTP. Poll the job endpoint.
4. No plugin framework. New capabilities are pipeline stages.
