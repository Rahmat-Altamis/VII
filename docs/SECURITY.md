# Security Model

## Threat model

1. Untrusted video bytes, container metadata, URLs, filenames, and
   webhook callbacks are hostile input.
2. Operator credentials (`MODEL_API_KEY`, service keys, DB URLs) must
   never reach logs, reports, error messages, or tracked files.
3. Consumers of the API server are mutually untrusted. Data must not
   leak across consumers.
4. The provider network path is trusted but metered, so every call
   goes through budgets, short timeouts, and typed errors.

## Credential sources

Provider key precedence (first hit wins):

1. Explicit key argument (library `VII(api_key=...)`, MCP
   `api_key` field).
2. `MODEL_API_KEY` env var.
3. OS keyring entry.
4. `~/.vii/credentials.json` with mode `0600`.

Consumer identity (VII API server callers) is separate:
`VII_CONSUMER_KEYS` mapping (`name:key`), `VII_API_KEYS`
(list), or single `VII_API_KEY`. When auth is off, identity comes
from the `X-Consumer` header or `VII_CONSUMER_ID`.

## Onboarding a new key

CLI (interactive, confirmation shown, secret never echoed):

```bash
vii credentials set     # prompts, validates, stores
vii credentials status  # source, endpoint, readiness tiers
vii credentials test    # safe live ping, only if explicitly run
```

The TUI offers the same flow via `/key set`. The desktop Settings
dialog supports view, update, and remove, with masked display.

## Secret handling rules

1. Never print or log the raw secret. `vii.logging_setup` redacts
   bearer tokens and key patterns at the handler level.
2. `/diagnostics` and `/status` expose source and shape only
   (presence, length class), never the value.
3. `.env.example` stays blank. Live `.env` is untracked and must
   never be staged. Tracked files are scanned for key patterns
   before release.
4. Credential stores are created with restrictive permissions
   (`0600` files, `0700` dirs). The remove command deletes
   both keyring and fallback entries.

## Input hardening (implemented)

1. URL ingestion: http and https only, DNS resolved and rejected on
   global address fail closed on DNS error, redirects revalidated
   (max 5), non HTML content sniffed, max body cap.
2. Uploads: extension allowlist, magic byte sniffing, max size cap
   enforced during streaming, randomized storage name.
3. Local paths (UI, CLI, MCP, library): existence, readability,
   size, extension, and container signature checks before any
   provider call. Symlinks are resolved; traversal outside the
   allowed root is rejected.
4. Webhooks: disabled unless `VII_WEBHOOK_ENABLED=true`, callback
   URLs SSRF validated, HMAC signed with `VII_WEBHOOK_SECRET`,
   verified with `hmac.compare_digest`.
5. API startup: `VII_REQUIRE_AUTH=true` without configured keys, or
   a bypass bind without auth, fails fast instead of serving open.
6. Concurrency: a singleton DB lock guards the SQLite dev path so
   parallel writes serialize safely.

## Live verification status

Provider call paths (upload, responses, transcription, search) are
live verified against the Meta Model API during the pilot runs;
see `data/evaluation/real_world_pilot/runs/` for redacted session
evidence. The routine test suite stays offline with mocked
transports and asserts secret redaction across log emitters. The
desktop UI remains mock backed and is not part of the verified
live path.

## Not covered

1. No per consumer rate limiting yet. Loopback throttle exists for
   abuse resistance.
2. No cost dashboard. Token and cost fields are recorded when the
   provider returns them, else explicitly absent.
3. Transcription session ids are logged but not persisted per job.
