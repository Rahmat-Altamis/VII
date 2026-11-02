# Synthetic Beta Benchmark v0.1

`synthetic_beta_v0.1.jsonl` is a **fully synthetic benchmark template** for
beta-testing Video Integrity Intelligence (VII). It contains 30 fictional
cases — 5 each of `verified_true`, `false_claim`, `misleading_context`,
`unverifiable`, `manipulated_media`, and `benign_out_of_scope`.

It is **not** real-world evaluation data, contains no media, no citations,
and no verification results, and must never be reported as detection
accuracy.

## Why JSONL here, when VII datasets are CSV?

VII's existing dataset subsystem (`src/vii/dataset/ingestion.py`,
`docs/DATASET.md`) is a CSV *inbox* for operator-supplied samples awaiting
annotation; it has no fields for expected labels, evidence requirements, or
confidence behaviour, and ingestion registers rows as user submissions.
Benchmark cases are a different artifact, so v0.1 is a separate, versioned
JSONL template validated by an extension of the same package
(`src/vii/dataset/benchmark.py`, reusing the CSV validator's `RowError`
line-error style). It is deliberately **not** placed at `data/dataset.csv`
and is never passed to `ingest_csv`, so synthetic cases cannot enter the
production/user Dataset Inbox.

## Schema (one JSON object per line)

| Field | v0.1 rule |
|---|---|
| `id` | `syn-v01-<category>-NN`, unique |
| `dataset_version` | exactly `"0.1"` |
| `sample_origin` | exactly `"synthetic"` (enforced) |
| `is_synthetic` | exactly `true` (enforced) |
| `category` | one of the six categories above |
| `claim_text` | short fictional claim; no URLs |
| `media_reference` | `null` — no authorised test asset exists |
| `expected_label` | fixed per category (table below) |
| `expected_confidence_behavior` | calibrated behaviour in prose; numeric probabilities are rejected |
| `evidence_requirements` | non-empty list: what a scored run must supply |
| `reference_sources` | `[]` — no sources have been genuinely verified |
| `expected_failure_modes` | non-empty list of pitfalls being tested |
| `notes` | purpose of the case; states the synthetic scenario |

### Field-name adaptations from existing VII vocabulary

`expected_label` reuses `vii.domain.enums.ClaimStatus` values where they
exist — `supported`, `contradicted`, `unverifiable` — and adds three
benchmark-only values for outcomes `ClaimStatus` cannot express:
`misleading_context` (context misuse), `media_manipulation_flag` (route to
origin/originality checks; **not** a finding that media was manipulated),
and `out_of_scope` (no checkable factual claim). `unverifiable` is kept
strictly distinct from `false_claim`/`contradicted`: the validator rejects
any category/label mismatch.

`expected_label` for `verified_true`/`false_claim` cases is a *scoring
target conditional on the listed `evidence_requirements` being supplied by
the benchmark operator in a scored run*. The template itself supplies no
evidence and asserts no real-world truth.

## Load and validate

```python
from pathlib import Path
from vii.dataset import load_benchmark

report = load_benchmark(Path("datasets/synthetic_beta_v0.1.jsonl"))
assert report.ok, report.as_dict()          # schema + safety invariants
for case in report.cases:
    display = case.as_public_display()       # always synthetic-labelled
```

A case can never be rendered as a real finding:
`vii.dataset.benchmark.to_verified_finding(case)` raises for every case,
and `as_public_display()` always returns `is_synthetic: True` and
`is_real_verified_finding: False`.

## Synthetic vs real-world data

| | This benchmark | Real evaluation data |
|---|---|---|
| Location | `datasets/synthetic_beta_v0.1.jsonl` | `data/dataset.csv` (operator-supplied) |
| Origin marker | `sample_origin="synthetic"`, `is_synthetic=true` on every row | registered via Dataset Inbox, `annotation_status='pending'` |
| Media / sources | none (`null` / `[]`) | operator-controlled references |
| Purpose | pipeline behaviour template (abstention, routing, labelling) | measuring real-world performance |

## Limitations

- Labels describe expected behaviour, not model results; running a model
  against these cases measures agreement with this template only.
- No case includes media, so manipulated-media cases test *routing and
  restraint* (flag for examination, conclude nothing), never detector
  accuracy.
- Claims use invented towns, clubs, stations, and office-holders. Any
  resemblance to real entities is unintended; no real person is alleged
  to have done anything.

Tests: `tests/test_synthetic_benchmark.py`.
