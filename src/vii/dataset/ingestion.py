"""First-class dataset CSV subsystem: schema, rows, identifiers, evaluation separation.

Canonical location: ``data/dataset.csv`` (override with ``DATASET_CSV_PATH``).
The application starts normally when the file is absent; nothing here runs at
import or startup, and ingestion NEVER starts video analysis, it only
validates and (on explicit request) registers rows into the consumer's
Unclassified Dataset Inbox (``dataset_samples``, ``annotation_status='pending'``).

CSV schema (UTF-8, header required, comma dialect by default):

  video_id     (required) stable external identifier, unique per consumer
  source_url   (optional) http(s) URL of the video/post; may be empty
  platform     (optional) e.g. instagram | facebook | generic
  storage_ref  (optional) local path or s3:// URI already under operator control
  sha256       (optional) 64-char hex digest of the original file, if known
  duration_s   (optional) non-negative number of seconds, if known
  title        (optional) human-readable label, stored in meta_json

Unknown columns are reported as warnings, never silently dropped.
Row-level problems are collected as RowError(line, column, message) and never
abort the whole file unless the header itself is invalid.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS: tuple[str, ...] = ("video_id",)
KNOWN_COLUMNS: tuple[str, ...] = (
    "video_id", "source_url", "platform", "storage_ref", "sha256",
    "duration_s", "title",
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass
class RowError:
    line: int  # 1-based CSV line number (header is line 1)
    column: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"line": self.line, "column": self.column, "message": self.message}


@dataclass
class ParsedRow:
    line: int
    video_id: str
    source_url: str = ""
    platform: str = ""
    storage_ref: str = ""
    sha256: str = ""
    duration_s: float = 0.0
    title: str = ""

    def meta(self) -> dict[str, Any]:
        return {"title": self.title} if self.title else {}


@dataclass
class ValidationReport:
    path: str
    exists: bool
    encoding: str = "utf-8-sig"
    dialect: str = "excel"
    header: list[str] = field(default_factory=list)
    total_rows: int = 0
    valid_rows: int = 0
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_video_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exists and not self.errors and not self.duplicate_video_ids

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "ok": self.ok,
            "encoding": self.encoding,
            "dialect": self.dialect,
            "header": self.header,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "errors": [e.as_dict() for e in self.errors],
            "warnings": self.warnings,
            "duplicate_video_ids": self.duplicate_video_ids,
        }


def _detect_dialect(sample: str) -> tuple[str, type[csv.Dialect]]:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return type(dialect).__name__, dialect  # type: ignore[return-value]
    except csv.Error:
        return "excel", csv.excel


def validate_csv(path: str | Path) -> ValidationReport:
    """Validate a dataset CSV without touching the database or any video.

    Missing file is a normal state (report.exists=False), not an exception,
    the app must start and run with no dataset present.
    """
    p = Path(path)
    report = ValidationReport(path=str(p), exists=p.is_file())
    if not report.exists:
        report.warnings.append(
            f"dataset file not found at {p}, this is expected before a "
            "dataset is supplied; the application runs without it")
        return report

    raw = p.read_bytes()
    # Explicit encoding: UTF-8 with optional BOM. Decode errors are reported
    # as a single file-level error rather than crashing ingestion.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        report.errors.append(RowError(0, "", f"file is not valid UTF-8: {exc}"))
        return report

    dialect_name, dialect = _detect_dialect(text[:4096])
    report.dialect = dialect_name
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if reader.fieldnames is None:
        report.errors.append(RowError(1, "", "missing header row"))
        return report
    header = [h.strip() if h else "" for h in reader.fieldnames]
    report.header = header
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        report.errors.append(RowError(
            1, ",".join(missing),
            f"missing required column(s): {', '.join(missing)} "
            f"(required: {', '.join(REQUIRED_COLUMNS)})"))
        return report
    unknown = [h for h in header if h and h not in KNOWN_COLUMNS]
    if unknown:
        report.warnings.append(f"unknown column(s) ignored by ingestion: {', '.join(unknown)}")

    seen: dict[str, int] = {}
    for idx, raw_row in enumerate(reader):
        line = idx + 2  # header is line 1
        report.total_rows += 1
        row = {(k.strip() if k else ""): (v.strip() if isinstance(v, str) else v)
               for k, v in raw_row.items()}
        # csv.DictReader puts surplus fields under None key.
        if None in row:
            report.errors.append(RowError(line, "", "row has more fields than the header"))
            continue
        video_id = (row.get("video_id") or "").strip()
        if not video_id:
            report.errors.append(RowError(line, "video_id", "video_id is required and must be non-empty"))
            continue
        if len(video_id) > 128:
            report.errors.append(RowError(line, "video_id", "video_id exceeds 128 characters"))
            continue
        if video_id in seen:
            report.duplicate_video_ids.append(video_id)
            report.errors.append(RowError(
                line, "video_id",
                f"duplicate video_id {video_id!r} (first seen on line {seen[video_id]})"))
            continue
        seen[video_id] = line

        source_url = (row.get("source_url") or "").strip()
        if source_url and not source_url.startswith(("http://", "https://")):
            report.errors.append(RowError(line, "source_url", "source_url must start with http:// or https://"))
            continue
        sha256 = (row.get("sha256") or "").strip().lower()
        if sha256 and not _SHA256_RE.match(sha256):
            report.errors.append(RowError(line, "sha256", "sha256 must be 64 hex characters"))
            continue
        duration_raw = (row.get("duration_s") or "").strip()
        duration_s = 0.0
        if duration_raw:
            try:
                duration_s = float(duration_raw)
            except ValueError:
                report.errors.append(RowError(line, "duration_s", "duration_s must be a number"))
                continue
            if duration_s < 0:
                report.errors.append(RowError(line, "duration_s", "duration_s must be >= 0"))
                continue

        report.rows.append(ParsedRow(
            line=line,
            video_id=video_id,
            source_url=source_url,
            platform=(row.get("platform") or "").strip(),
            storage_ref=(row.get("storage_ref") or "").strip(),
            sha256=sha256,
            duration_s=duration_s,
            title=(row.get("title") or "").strip(),
        ))
    report.valid_rows = len(report.rows)
    return report


def file_fingerprint(path: str | Path) -> str:
    """SHA-256 of the CSV file itself, for run provenance (not a video hash)."""
    p = Path(path)
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class IngestResult:
    report: ValidationReport
    dry_run: bool = True
    registered: int = 0
    skipped_duplicates: int = 0
    consumer: str = "default"

    def as_dict(self) -> dict[str, Any]:
        d = self.report.as_dict()
        d.update({
            "dry_run": self.dry_run,
            "registered": self.registered,
            "skipped_duplicates": self.skipped_duplicates,
            "consumer": self.consumer,
        })
        return d


def ingest_csv(path: str | Path, session_factory, consumer: str = "default",
               *, dry_run: bool = True) -> IngestResult:
    """Validate then optionally register rows into the Dataset Inbox.

    dry_run=True (the default) performs full validation and duplicate checks
    against the database WITHOUT writing. dry_run=False registers each valid,
    non-duplicate row via DatasetRepo (annotation_status='pending'). This
    function never creates analyses, downloads media, or calls a model.
    """
    from vii.persistence.repositories import DatasetRepo

    report = validate_csv(path)
    result = IngestResult(report=report, dry_run=dry_run, consumer=consumer or "default")
    if not report.exists or report.errors:
        return result
    with session_factory() as db:
        repo = DatasetRepo(db)
        for row in report.rows:
            existing = repo.get_by_consumer_video(result.consumer, row.video_id)
            if existing is not None:
                result.skipped_duplicates += 1
                continue
            if dry_run:
                continue
            repo.register(
                result.consumer, row.video_id, row.source_url, row.platform,
                row.storage_ref, row.sha256, row.duration_s, row.meta(),
            )
            result.registered += 1
    return result
