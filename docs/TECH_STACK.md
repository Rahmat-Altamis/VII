# Tech Stack

This file lists the technologies VII actually uses and the state of
each integration. Stale planning notes were removed. Claims below
were rechecked against the code and the pilot runs.

## Language and packaging

1. Python 3.10 or newer, packaged with setuptools via
   `pyproject.toml`. Install flavors: core library by default,
   plus optional extras `api`, `db`, `provider`, `media`, `app`,
   `desktop`, `mcp`, `dev`, `test`.
2. Runtime entry points: `vii` (CLI plus TUI), `vii-mcp` (agent
   tools server), `vii-api` (HTTP server), `vii-worker` (queue
   worker, same process model as the API worker).
3. Lint and format: Ruff (`ruff check src tests`), plus pytest
   for the 255 test suite.

## HTTP API

1. FastAPI plus uvicorn (`.[api]`). Versioned `/v1` router is the
   contract; legacy unversioned routes are deprecated but auth
   hardened identically.
2. Pydantic v2 request and response models in `src/vii/api/`.
3. Auth: bearer service keys with constant time compare, consumer
   scoping on every read, loopback dev bypass only when auth is
   off. Pydantic v1 style validators were migrated; the codebase
   compiles warning free on Pydantic v2.

## Persistence

1. SQLAlchemy 2.x models plus repositories (`.[db]`).
2. SQLite for local dev and tests (`data/vii.db` default).
   PostgreSQL URLs parse but no driver ships, so PostgreSQL
   remains model compatible only, not runnable on stock install.
3. Alembic revisions for shared databases (`0001` baseline,
   `0002` evidence relationship columns). Startup also applies
   idempotent `migrate()` for zero config dev databases.
4. SHA 256 keyed cache rows for understanding results.

## Provider integrations (Meta Model API, live verified)

Base URL `https://api.meta.ai/v1`, bearer auth via `MODEL_API_KEY`,
all I/O confined to `src/vii/meta/`. The pilot smoke and repair
runs verified each path below against the real API with redacted
session evidence under `data/evaluation/real_world_pilot/runs/`.

1. Files upload. Binary upload with purpose `user_data`. Verified.
2. Responses create (Muse Spark). Video understanding, claim
   extraction, and web search evidence retrieval. Verified.
3. Responses create (SAM). Visual perception over sampled frames.
   Verified with timeout degradation.
4. ASR transcribe. `POST {base}/asr/transcribe` multipart with a
   JSON request part plus normalized WAV audio part. Verified
   with diarization turns plus speaker labels.
5. SDK retry posture. SDK level retries forced off
   (`max_retries=0`); one VII owned retry layer with short
   timeouts, no retry on 400, 401, 403, 404, or 413, no reupload
   on retry, transcription short circuit on 401 and 403.

## Media pipeline

1. ffprobe for duration, codec, resolution, fps, and frame counts.
2. FFmpeg for frame indexing plus WAV normalization (mono, 16 bit
   PCM, 24 kHz) ahead of ASR.
3. PyAV free design: frame indexing shells to FFmpeg so installs
   stay light; no OpenCV or torch in the dependency tree.
4. Native MP4 signature parsing allows basic ingestion even when
   FFmpeg is absent.

## Terminal and agent surfaces

1. TUI (`vii tui`): stdlib only, Claude Code style agent console
   with slash commands, fast screen plus deep check, follow ups,
   credential onboarding, and readiness display.
2. CLI (`vii check`, `vii interactive`, `vii credentials`): argparse
   only, JSON output plus exit codes `0/2/3/4` for scripting.
3. MCP server (`vii-mcp`): stdio JSON RPC with four tools
   (`vii_quick_look`, `vii_check`, `vii_follow_up`,
   `vii_key_status`), caller supplied key, no env required.
4. Desktop UI (PySide6, `.[desktop]`): settings plus viewer only.
   Mock backed, stale relative to the pipeline, not live verified.

## AI origin and spam screening

1. AI origin score: hosted VLM frame judge sampled over N frames
   (default 5) with a tuned threshold (default `0.6`). Calibrated
   on the 975 image reference set (`data/ai_images/`) at 0.80
   sample accuracy. Reported as probability plus band, never as
   proof.
2. Spam score: local heuristic screen over title, description,
   transcript, and visual repetition signals. Reported as
   probability with matched reasons.
3. Both scores feed the assessment verdict as signals, never as
   sole determinants.

## Testing posture

1. `pytest` with mocked provider transports. No test requires a
   key or network. Live checks are explicit opt in scripts only.
2. Hermetic settings tests (`_env_file=None`) guard the no key
   path. Redaction tests cover every log emitter.
3. Migration tests run old schema SQLite fixtures through
   `migrate()` plus Alembic head.
4. Clean env verification: install `.[app,mcp]` plus dev extras
   in a fresh venv, run the suite plus Ruff, exercise the TUI,
   CLI, library, and MCP server with PySide6 absent.

## Known limits

1. Evidence search needs the live provider; offline runs record
   `performed:false` with an explicit note.
2. Frame coverage honesty: decoded frames are local fact,
   provider analyzed frames are provider reported only. No full
   frame AI claim without provider proof.
3. Transcription session ids are logged, not persisted per job.
4. No per consumer rate limiting and no cost dashboard yet.
