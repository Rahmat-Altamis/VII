# Dataset Guide

VII treats video records as its dataset. There are two stores:
inbox samples (small registry backed by the configured database)
and CSV rows (validated by the `DatasetService`).
No ground truth video labels ship with the repository.

There is also an AI image reference set used only to calibrate the
AI origin scores (see section 7). It is not a video dataset.

## 1. CSV schema (video records)

Required columns (header names are exact, comma separated):

1. `video_id`
2. `platform`
3. `url`
4. `sha256` (64 lowercase hex chars)
5. `acquisition_timestamp` (ISO 8601, past or present)
6. `license_or_tos_basis` (free text; include a review date)

Optional columns: `test_split` (`train` or `test`; blank becomes
`test`), `query`, `status` (`found`, `takedown`, or `geo_block`;
blank becomes `found`).

Rules. Blank line detection reports 1 based line numbers. Whitespace
is stripped; values are case sensitive except `test_split` and
`status`, which are lowercased. Validation caps: 10 refresh rows,
50 ingest rows, 100000 CSV bytes, 1 year max age. Placeholder rows
(`video_id` or URL containing the EXAMPLE.COM host) fail with
actionable hints.

## 2. Inbox samples (database registry)

Register with `POST /v1/datasets/samples`. A `local_path` must resolve
under `VII_STORAGE_DIR` (upload first through `/v1/uploads`). Reads
are consumer scoped: consumers see only their own samples.

## 3. Real world pilot (operational eval set)

Created by `scripts/build_real_world_pilot.py` from local MP4s.

```bash
python scripts/build_real_world_pilot.py --source ~/Downloads --glob "*.mp4" --execute
```

Outputs under `data/evaluation/real_world_pilot/`:

1. `README.md`: pilot notes.
2. `dataset_manifest.json`: inventory plus provenance.
3. `videos.jsonl`: one record per video.
4. `annotations/`: per video annotation JSON.
5. `frames/`: per frame index JSONL.
6. `runs/`: analysis runs plus reports.

The script never moves, renames, or edits the source MP4s.

## 4. Dataset quick checks

```bash
python3 -m vii.main --validate-dataset
python3 -m vii.main --validate-dataset --dataset-csv path/to/file.csv
```

Validates the configured CSV (`DATASET_CSV_PATH`,
default `data/dataset.csv`). A missing file is informational, never
an error. API equivalents: `GET /v1/datasets/check` and
`POST /v1/datasets/ingest-csv?dry_run=true|false`.

## 5. Dataset ingestion

`POST /v1/datasets/ingest-csv?dry_run=true` returns validated plus
preview rows. `dry_run=false` registers rows idempotently into the
caller inbox. Ingestion never starts analysis.

## 6. Content comparison (dataset backed originality)

`POST /v1/content/compare` supports SHA 256 pair matching and
two report pHash plus SHA comparison. Scoring:
same SHA `1.0`; same pHash but different SHA `0.85`; otherwise
similarity based on pHash Hamming distance (`1.0` minus
distance/64.0, floored at `0.0`) plus a capped duration proximity
boost of at most `0.05`.

## 7. AI image reference set

`scripts/build_ai_image_dataset.py` indexes a zip of real plus AI
photos into `data/ai_images/` (`dataset_manifest.json`,
`images.jsonl`, `files/`). `scripts/eval_ai_detector_sample.py`
evaluates the calibrated AI origin score on a sample and writes
`eval_report.json` with accuracy plus a confusion matrix. The
detector is a hosted model frame judge with a tuned threshold
(default `0.6`); scores below the threshold on some AI samples are
expected for near photorealistic images.

## 8. Statistical honesty rules

1. New evaluation code must synthesize counts only from stored run
   rows. Never invent totals from claims or assessments.
2. UI and API consumers read stats from the repository layer, never
   from aggregate caches.
3. Never fabricate metrics: token counts, costs, timing, and
   frame coverage must come from the actual provider response
   or be explicitly absent.
4. Distinguish decoded frames (local ffprobe) from provider analyzed
   frames (reported by the provider only).
5. Do not claim full frame AI coverage unless the provider proves it.
   The pilot records the distinction in every run ledger.
