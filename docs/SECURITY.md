# Security

VII handles untrusted URLs, uploaded media, and API credentials. Security is
enforced in code (fail-closed), not just documented here. This file describes
the boundaries; `tests/test_auth_hardening.py` is the executable proof for
the authentication rules.

## Authentication & consumer isolation

- **Loopback-only unauthenticated dev.** With `VII_REQUIRE_AUTH=false`, the
  configured bind host must be loopback (`127.0.0.0/8`, `::1`, `localhost`,
  including numeric shorthands) — `Settings` raises at startup otherwise.
  Non-loopback binds require `VII_REQUIRE_AUTH=true` **with** keys configured
  (`VII_API_KEYS` and/or well-formed `VII_CONSUMER_KEYS`); malformed-only
  values count as none.
- **Identity.** `VII_CONSUMER_KEYS` (`name:key`) gives stable operator-assigned
  consumer names. Bare `VII_API_KEYS` derive identity as
  `key-<full 64-hex SHA-256>` — collision-resistant, stable across restarts,
  and the raw key never appears in logs, responses, or stored records.
- **No header spoofing.** With auth enabled, `X-Consumer` alone authenticates
  nobody, and a valid key + forged `X-Consumer` still resolves to the key's
  identity. Cross-consumer job/dataset/report access returns `404`.
- **Legacy routes** enforce the same identity as `/v1` (they previously
  ignored auth entirely — fixed; see `docs/API.md`).

## Secrets

- Keys come from env (`MODEL_API_KEY`, tokens) or the OS keyring via
  `vii.keystore` (0600-file fallback under the storage dir). Never committed,
  never in `.env` when saved from Settings (stored in keyring instead).
- `vii.logging_setup` redacts key/token material from all `vii.*` logs;
  `Settings.redacted()` exposes only counts/sources. Diagnostics endpoints
  return redacted settings only.
- Fixtures/docs use synthetic values (`sk-...` placeholders) exclusively.

## Input, SSRF & outbound requests

- **Source URLs** pass `vii.media.ingestion._ssrf_check`: localhost,
  private/loopback/link-local/multicast/reserved resolutions are refused.
  Page URLs (Instagram/Facebook posts) are never fetched with unofficial
  downloaders — only authorized platform APIs or a required local upload.
- **Webhooks** are disabled by default (`VII_WEBHOOK_ENABLED=true` to enable).
  Targets must be public http(s): localhost/private/link-local/metadata IPs,
  internal suffixes, and all redirects are refused, with host re-validation
  after any response. Payloads are HMAC-signed.
- **Uploads** stream in 1 MiB chunks with the `VII_MAX_UPLOAD_MB` cap enforced
  during the write (partial files deleted on overflow), extension allowlist,
  server-generated filenames. No user-controlled path is ever written.
- **Dataset `local_path`** must resolve under `VII_STORAGE_DIR`; arbitrary
  server paths are refused. Dataset CSV paths come from operator config
  (`DATASET_CSV_PATH`), not request input.

## Media & process safety

- FFmpeg/ffprobe run via `subprocess` with `shell=False`, argument lists,
  and timeouts (`vii.media.ffmpeg`). No shell interpolation of filenames.
- Original uploads are preserved; converted derivatives are separate files
  with separate SHA-256 hashes. Originality checks use exact + perceptual
  hashes, never a fabricated AI-detector verdict.

## Database & workers

- All DB access is parameterized ORM via repositories — no string-built SQL.
- Worker retries are bounded (`max_retries=2`), failures persisted to
  `processing_logs`, cancellation is cooperative and consumer-checked at the
  API layer. Worker threads are daemons scoped to the app lifespan.
- Reports/exports live under `storage_dir/exports/` with job-id filenames;
  report reads are consumer-checked before any file is served.

## Known limits (honest)

- Live Meta integration (Responses API `input_video`/`file_id`, web search,
  transcription shapes) is **mock-verified only** in this environment — no
  credentials were available. Treat live behavior as unverified until the
  opt-in checks in `docs/DEVELOPMENT.md` are run.
- No rate limiting or request-size middleware beyond the upload cap exists
  yet; put a reverse proxy in front for internet-facing deployments.
- S3 storage (`vii.storage`) is an optional backend; local disk is default.
