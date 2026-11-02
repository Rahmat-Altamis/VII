# Video Integrity Intelligence (VII)

Evidence-first video intelligence: paste a public video URL or upload a local
file → the video is understood natively → factual claims are extracted →
evidence is retrieved with URL citations → every claim gets a status
(**supported / contradicted / mixed / insufficient / unverifiable**) backed by
cited sources. Five assessment dimensions stay separate — never one fake
real/fake score.

API-first modular monolith (FastAPI + SQLAlchemy), with an optional PySide6
desktop UI. VII is **online-first**: real provider-backed analysis is the
default, and a missing `MODEL_API_KEY` fails provider-backed analysis with a
typed `ProviderConfigurationError` — it never substitutes fixtures. A
synthetic demo is available only as an explicit opt-in (`VII_DEMO_MODE=true`
or `--demo`) and is labeled synthetic in every output.

## Quick start

```bash
pip install -e ".[dev]"        # add ,desktop for the PySide6 UI
cp .env.example .env           # set MODEL_API_KEY for real analysis
./scripts/run_demo.sh          # explicit SYNTHETIC demo (fixtures, not analysis)
./scripts/run_api.sh           # FastAPI on http://127.0.0.1:8765 (docs: /docs)
./scripts/run_ui.sh            # desktop app (provider-backed; demo only if opted in)
python3 -m pytest tests/ -q    # mocked tests only; no credits spent
```

## Dataset

Drop a real dataset at **`data/dataset.csv`** (or set `DATASET_CSV_PATH`),
then validate it — the app runs fine before the file exists and never starts
analysis on its own:

```bash
python3 -m vii.main --validate-dataset          # schema + row-error report
python3 -m vii.main --ingest-dataset --apply    # register into the inbox
```

Schema and workflow: [docs/DATASET.md](docs/DATASET.md). Template:
`data/dataset.example.csv`.

## Live Meta mode (optional, unverified in this environment)

```bash
# .env
MODEL_API_KEY=sk-...
META_BASE_URL=https://api.meta.ai/v1
META_MODEL=muse-spark-1.3
META_TRANSCRIPTION_MODEL=muse-voice-transcribe-1.0
```

URL input is sent via `input_video`/`video_url`; local files via the Files
API (`file_id`); evidence via `web_search` with persisted `url_citation`s.
Live behavior is covered by mocks in tests — run the opt-in checks in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) with a real key before relying on it.

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Boundaries, dependency direction, data/job flow, decisions |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Selected technologies and rejected alternatives |
| [docs/API.md](docs/API.md) | `/v1` contract, auth, errors, dataset endpoints |
| [docs/DATASET.md](docs/DATASET.md) | CSV schema, validation, ingestion, evaluation workflow |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, testing, linting, migrations |
| [docs/SECURITY.md](docs/SECURITY.md) | Auth, isolation, SSRF/upload/webhook boundaries |

## Layout

`src/vii/` — `config.py` · `domain/` (Pydantic contracts) · `persistence/`
(SQLAlchemy + repositories; Alembic migrations) · `meta/` (provider adapter) ·
`media/` (ingestion, SSRF guard, ffmpeg, hashing) · `evidence/` ·
`verification/` · `integrity/` · `dataset/` (CSV) · `reports/` · `api/`
(FastAPI `/v1` + deprecated legacy) · `application/` (pipeline, worker) ·
`ui/` (optional desktop).
