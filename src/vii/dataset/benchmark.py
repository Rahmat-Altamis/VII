"""Synthetic beta benchmark (v0.1): JSONL template cases, never real findings.

This EXTENDS ``vii.dataset`` alongside the CSV inbox in
``vii.dataset.ingestion``; it is not a competing ingestion format:

* The CSV inbox registers real, operator-supplied samples for annotation.
* This module validates a versioned, fully synthetic *benchmark template*
  (``datasets/synthetic_beta_v0.1.jsonl``): fictional claims with expected
  assessment *behavior*, no media, no citations, no real-world results.

Safety invariants enforced here (not left to convention):

* every record must declare ``sample_origin == "synthetic"`` and
  ``is_synthetic is True``, a record claiming any other origin is rejected,
  so a benchmark case cannot silently pass as a real sample;
* ``to_verified_finding`` always refuses: a synthetic case can never be
  converted into, or displayed as, a real verified finding;
* ``media_reference`` must be null and ``reference_sources`` must be empty
  in v0.1, no asset has been examined and no source has been verified, so
  records may not imply either;
* ``expected_confidence_behavior`` is calibrated *behavior* prose and may
  not contain a fabricated numeric probability (percent or 0.x figure).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vii.dataset.ingestion import RowError

BENCHMARK_VERSION = "0.1"

CATEGORIES: tuple[str, ...] = (
    "verified_true",
    "false_claim",
    "misleading_context",
    "unverifiable",
    "manipulated_media",
    "benign_out_of_scope",
)

# Adapted to the project's ClaimStatus vocabulary (vii.domain.enums) where a
# claim status exists; three benchmark-only outcomes cover cases ClaimStatus
# cannot express (context misuse, media-manipulation routing, out of scope).
EXPECTED_LABELS: tuple[str, ...] = (
    "supported",              # ClaimStatus.SUPPORTED
    "contradicted",           # ClaimStatus.CONTRADICTED
    "misleading_context",     # benchmark-only: claim misuses real context
    "unverifiable",           # ClaimStatus.UNVERIFIABLE (never "contradicted")
    "media_manipulation_flag",  # benchmark-only: route to origin/originality
    "out_of_scope",           # benchmark-only: no verifiable factual claim
)

CATEGORY_EXPECTED_LABEL: dict[str, str] = {
    "verified_true": "supported",
    "false_claim": "contradicted",
    "misleading_context": "misleading_context",
    "unverifiable": "unverifiable",
    "manipulated_media": "media_manipulation_flag",
    "benign_out_of_scope": "out_of_scope",
}

REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "dataset_version", "sample_origin", "is_synthetic", "category",
    "claim_text", "media_reference", "expected_label",
    "expected_confidence_behavior", "evidence_requirements",
    "reference_sources", "expected_failure_modes", "notes",
)

_ID_RE = re.compile(r"^syn-v01-[a-z_]+-\d{2}$")
_PROBABILITY_RE = re.compile(r"(\d+(?:\.\d+)?\s*%|\b0\.\d+\b|\b1\.0\b)")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


@dataclass
class BenchmarkCase:
    id: str
    dataset_version: str
    sample_origin: str
    is_synthetic: bool
    category: str
    claim_text: str
    media_reference: Any
    expected_label: str
    expected_confidence_behavior: str
    evidence_requirements: list[str]
    reference_sources: list[str]
    expected_failure_modes: list[str]
    notes: str
    line: int = 0

    def as_public_display(self) -> dict[str, Any]:
        """Display-safe rendering: always labeled synthetic, never a finding."""
        return {
            "id": self.id,
            "display_label": "SYNTHETIC BENCHMARK CASE - not a real verified finding",
            "is_synthetic": True,
            "is_real_verified_finding": False,
            "category": self.category,
            "expected_label": self.expected_label,
            "claim_text": self.claim_text,
        }


def to_verified_finding(case: BenchmarkCase) -> dict[str, Any]:
    """Refuse unconditionally: synthetic cases are not real findings."""
    raise ValueError(
        f"synthetic benchmark case {case.id!r} can never be presented as a "
        "real verified finding")


@dataclass
class BenchmarkReport:
    path: str
    exists: bool
    cases: list[BenchmarkCase] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exists and not self.errors and not self.duplicate_ids

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.category] = counts.get(case.category, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "exists": self.exists, "ok": self.ok,
            "total_cases": len(self.cases),
            "category_counts": self.category_counts(),
            "errors": [e.as_dict() for e in self.errors],
            "duplicate_ids": self.duplicate_ids,
        }


def _validate_record(record: Any, line: int, seen: dict[str, int],
                     errors: list[RowError]) -> BenchmarkCase | None:
    def err(column: str, message: str) -> None:
        errors.append(RowError(line, column, message))

    if not isinstance(record, dict):
        err("", "record must be a JSON object")
        return None
    start = len(errors)
    for name in REQUIRED_FIELDS:
        if name not in record:
            err(name, f"missing required field: {name}")
    if len(errors) > start:
        return None

    case_id = record["id"]
    if not isinstance(case_id, str) or not _ID_RE.match(case_id):
        err("id", "id must match syn-v01-<category>-NN")
    elif case_id in seen:
        err("id", f"duplicate id {case_id!r} (first seen on line {seen[case_id]})")
    else:
        seen[case_id] = line

    if record["dataset_version"] != BENCHMARK_VERSION:
        err("dataset_version", f"dataset_version must be {BENCHMARK_VERSION!r}")
    # Synthetic-origin enforcement: anything else is rejected outright.
    if record["sample_origin"] != "synthetic":
        err("sample_origin", "sample_origin must be 'synthetic' for benchmark cases")
    if record["is_synthetic"] is not True:
        err("is_synthetic", "is_synthetic must be true for benchmark cases")

    category = record["category"]
    if category not in CATEGORIES:
        err("category", f"category must be one of {', '.join(CATEGORIES)}")
    label = record["expected_label"]
    if label not in EXPECTED_LABELS:
        err("expected_label", f"expected_label must be one of {', '.join(EXPECTED_LABELS)}")
    elif category in CATEGORY_EXPECTED_LABEL and label != CATEGORY_EXPECTED_LABEL[category]:
        err("expected_label",
            f"category {category!r} requires expected_label "
            f"{CATEGORY_EXPECTED_LABEL[category]!r}, got {label!r} "
            "(unverifiable must stay distinct from false_claim)")

    claim = record["claim_text"]
    if not isinstance(claim, str) or not claim.strip():
        err("claim_text", "claim_text must be a non-empty string")
    elif _URL_RE.search(claim):
        err("claim_text", "claim_text must not contain URLs (no invented citations)")

    if record["media_reference"] is not None:
        err("media_reference",
            "media_reference must be null in v0.1 (no authorized test asset exists)")
    if record["reference_sources"] != []:
        err("reference_sources",
            "reference_sources must be [] in v0.1 (no sources have been verified)")

    behavior = record["expected_confidence_behavior"]
    if not isinstance(behavior, str) or not behavior.strip():
        err("expected_confidence_behavior", "expected_confidence_behavior must be non-empty")
    elif _PROBABILITY_RE.search(behavior):
        err("expected_confidence_behavior",
            "expected_confidence_behavior must describe calibrated behavior, "
            "not a fabricated numeric probability")

    for name in ("evidence_requirements", "expected_failure_modes"):
        value = record[name]
        if (not isinstance(value, list) or not value
                or any(not isinstance(x, str) or not x.strip() for x in value)):
            err(name, f"{name} must be a non-empty list of non-empty strings")
    if not isinstance(record["notes"], str) or not record["notes"].strip():
        err("notes", "notes must be a non-empty string")

    if len(errors) > start:
        return None
    return BenchmarkCase(
        id=case_id, dataset_version=record["dataset_version"],
        sample_origin=record["sample_origin"], is_synthetic=True,
        category=category, claim_text=claim.strip(), media_reference=None,
        expected_label=label, expected_confidence_behavior=behavior.strip(),
        evidence_requirements=list(record["evidence_requirements"]),
        reference_sources=[], expected_failure_modes=list(record["expected_failure_modes"]),
        notes=record["notes"].strip(), line=line)


def validate_records(records: list[Any], path: str = "<records>") -> BenchmarkReport:
    """Validate already-parsed benchmark records (pure, no file I/O)."""
    report = BenchmarkReport(path=path, exists=True)
    seen: dict[str, int] = {}
    for idx, record in enumerate(records):
        case = _validate_record(record, idx + 1, seen, report.errors)
        if case is not None:
            report.cases.append(case)
    report.duplicate_ids = sorted(
        {e.message.split("'")[1] for e in report.errors
         if e.column == "id" and "duplicate id" in e.message})
    return report


def load_benchmark(path: str | Path) -> BenchmarkReport:
    """Load and validate a benchmark JSONL file. Missing file is reported,
    not raised, mirroring vii.dataset.ingestion.validate_csv."""
    p = Path(path)
    report = BenchmarkReport(path=str(p), exists=p.is_file())
    if not report.exists:
        return report
    records: list[Any] = []
    for idx, raw_line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        line = idx + 1
        if not raw_line.strip():
            continue
        try:
            records.append(json.loads(raw_line))
        except json.JSONDecodeError as exc:
            report.errors.append(RowError(line, "", f"invalid JSON: {exc}"))
    parsed = validate_records(records, path=str(p))
    report.cases = parsed.cases
    report.errors = report.errors + parsed.errors
    report.duplicate_ids = parsed.duplicate_ids
    return report
