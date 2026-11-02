# Dataset Guide

VII is ready for a real evaluation dataset **without code changes**. This
document is the contract: file location, CSV schema, validation, and what
happens (and does not happen) when you supply data.

## Location

| | |
|---|---|
| **Default path** | `data/dataset.csv` (relative to the project root) |
| **Override** | Environment variable `DATASET_CSV_PATH` (see `.env.example`) |
| **Template** | `data/dataset.example.csv` (header only — no sample records) |

The application **starts and runs normally when `data/dataset.csv` is
absent**. Nothing is read at startup, no fake records are created, and no
evaluation results are invented. Supplying the file never auto-starts video
analysis.

## CSV schema

UTF-8 (BOM tolerated), header row required, comma dialect by default
(`;`, tab, and `|` are sniffed). Implementation: `vii.dataset.ingestion`.

| Column | Required | Rules |
|---|---|---|
| `video_id` | **Yes** | Stable external identifier; non-empty, ≤128 chars, unique within the file and per consumer in the inbox. |
| `source_url` | No | Must start with `http://` or `https://` when present. |
| `platform` | No | Free text, e.g. `instagram`, `facebook`, `generic`. |
| `storage_ref` | No | Local path or `s3://` URI already under operator control. |
| `sha256` | No | Exactly 64 hex characters when present (lowercased on ingest). |
| `duration_s` | No | Non-negative number when present. |
| `title` | No | Human-readable label; stored in the sample's `meta_json`. |

Unknown columns produce **warnings**, not failures. Every row problem is
reported with its 1-based line number (header = line 1), column, and message;
one bad row never hides errors in later rows. In-file duplicate `video_id`s
are errors. A file that is not valid UTF-8 fails as a single file-level error.

Example (synthetic):

```csv
video_id,source_url,platform,storage_ref,sha256,duration_s,title
v001,https://example.com/clip-a.mp4,generic,,,,Intro clip
v002,,instagram,,,42.0,Second clip
```

## Validate (no side effects)

```bash
# configured path (DATASET_CSV_PATH or data/dataset.csv)
python3 -m vii.main --validate-dataset
python3 -m vii.main --validate-dataset path/to/other.csv
# API equivalent (authenticated): GET /v1/datasets/check
```

Exit code `0` = valid **or absent** (both are normal); `2` = file exists
with schema/row errors. Output is a JSON report: header, row counts,
per-row errors, warnings, duplicate ids.

## Ingest into the Dataset Inbox

Ingestion registers rows as `dataset_samples` with
`annotation_status='pending'` — source data, processing runs, and evaluation
outputs stay separate. It is **idempotent per (consumer, `video_id`)**:
re-ingesting skips existing rows instead of duplicating them.

```bash
python3 -m vii.main --ingest-dataset            # dry-run preview (default)
python3 -m vii.main --ingest-dataset --apply    # actually register rows
# API: POST /v1/datasets/ingest-csv?dry_run=true|false
```

Ingestion never downloads media, creates analyses, or calls a model.

## After validation: the evaluation workflow (future phase)

1. Validate the CSV (above) until the report is clean.
2. Ingest with `--apply`; confirm counts via `GET /v1/datasets/search`.
3. Only then, as a separate deliberate step, create analyses for selected
   samples (`POST /v1/analyses`) — this is the future video-analysis phase
   and is out of scope for the current infrastructure work.
4. Compare persisted JSON reports against dataset labels offline; keep
   labels (`labels_json`, human-reviewed) separate from model output.

## Tests

`tests/test_dataset_ingestion.py` covers: missing-file normal state, valid
parsing, header errors, per-line row errors, duplicates, unknown-column
warnings, dry-run purity, apply idempotency, and consumer isolation.
Synthetic fixtures only.
