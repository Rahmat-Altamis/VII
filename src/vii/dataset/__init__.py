"""Dataset subsystem: CSV schema, validation, and inbox ingestion.

See vii.dataset.ingestion for the canonical CSV contract and
docs/DATASET.md for the operator workflow. Nothing in this package runs
at application startup and nothing here starts video analysis.
"""
from vii.dataset.ingestion import (
    KNOWN_COLUMNS,
    REQUIRED_COLUMNS,
    IngestResult,
    ParsedRow,
    RowError,
    ValidationReport,
    file_fingerprint,
    ingest_csv,
    validate_csv,
)

__all__ = [
    "KNOWN_COLUMNS",
    "REQUIRED_COLUMNS",
    "IngestResult",
    "ParsedRow",
    "RowError",
    "ValidationReport",
    "file_fingerprint",
    "ingest_csv",
    "validate_csv",
]
