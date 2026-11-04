"""Synthetic beta benchmark v0.1: schema, safety invariants, display guard.

Ships no media, calls no provider, and asserts only template behaviour,
never real-world detection accuracy.
"""
import copy
import json
from pathlib import Path

import pytest

from vii.dataset.benchmark import (
    CATEGORIES,
    CATEGORY_EXPECTED_LABEL,
    load_benchmark,
    to_verified_finding,
    validate_records,
)

BENCHMARK_PATH = Path(__file__).resolve().parent.parent / "datasets" / "synthetic_beta_v0.1.jsonl"


def _raw_records():
    return [json.loads(line) for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _one_valid() -> dict:
    return copy.deepcopy(_raw_records()[0])


def _errors_for(record) -> list:
    return validate_records([record]).errors


def test_shipped_benchmark_is_valid_and_balanced():
    report = load_benchmark(BENCHMARK_PATH)
    assert report.ok, report.as_dict()
    assert len(report.cases) == 30
    assert report.category_counts() == {category: 5 for category in CATEGORIES}
    ids = [c.id for c in report.cases]
    assert len(ids) == len(set(ids)) == 30


def test_shipped_cases_are_unmistakably_synthetic_and_asset_free():
    report = load_benchmark(BENCHMARK_PATH)
    for case in report.cases:
        assert case.is_synthetic is True
        assert case.sample_origin == "synthetic"
        assert case.dataset_version == "0.1"
        assert case.media_reference is None
        assert case.reference_sources == []
        assert case.expected_label == CATEGORY_EXPECTED_LABEL[case.category]
        assert case.evidence_requirements and case.expected_failure_modes


def test_missing_field_is_rejected():
    record = _one_valid()
    del record["claim_text"]
    errors = _errors_for(record)
    assert any(e.column == "claim_text" and "missing required field" in e.message for e in errors)


def test_invalid_category_and_label_are_rejected():
    record = _one_valid()
    record["category"] = "definitely_real_news"
    assert any(e.column == "category" for e in _errors_for(record))

    record = _one_valid()
    record["expected_label"] = "totally_fake"
    assert any(e.column == "expected_label" for e in _errors_for(record))


def test_category_label_mismatch_is_rejected():
    record = _one_valid()
    record["category"] = "false_claim"  # record still expects "supported"
    assert any(e.column == "expected_label" for e in _errors_for(record))


def test_duplicate_ids_are_rejected():
    record = _one_valid()
    report = validate_records([record, copy.deepcopy(record)])
    assert not report.ok
    assert report.duplicate_ids == [record["id"]]


def test_synthetic_origin_is_enforced():
    record = _one_valid()
    record["is_synthetic"] = False
    assert any(e.column == "is_synthetic" for e in _errors_for(record))

    record = _one_valid()
    record["sample_origin"] = "real_world"
    assert any(e.column == "sample_origin" for e in _errors_for(record))

    record = _one_valid()
    record["dataset_version"] = "9.9"
    assert any(e.column == "dataset_version" for e in _errors_for(record))


def test_no_fabricated_assets_citations_or_probabilities():
    record = _one_valid()
    record["media_reference"] = "some/unexamined.mp4"
    assert any(e.column == "media_reference" for e in _errors_for(record))

    record = _one_valid()
    record["reference_sources"] = ["invented citation"]
    assert any(e.column == "reference_sources" for e in _errors_for(record))

    record = _one_valid()
    record["expected_confidence_behavior"] = "Report this at 95% confidence."
    assert any(e.column == "expected_confidence_behavior" for e in _errors_for(record))

    record = _one_valid()
    record["claim_text"] = "See the proof at https://example.invalid/proof"
    assert any(e.column == "claim_text" for e in _errors_for(record))


def test_unverifiable_stays_distinct_from_false_claim():
    report = load_benchmark(BENCHMARK_PATH)
    unverifiable = [c for c in report.cases if c.category == "unverifiable"]
    false_claims = [c for c in report.cases if c.category == "false_claim"]
    assert unverifiable and false_claims
    assert all(c.expected_label == "unverifiable" for c in unverifiable)
    assert all(c.expected_label == "contradicted" for c in false_claims)
    assert {c.id for c in unverifiable}.isdisjoint(c.id for c in false_claims)


def test_synthetic_case_cannot_be_displayed_as_real_verified_finding():
    report = load_benchmark(BENCHMARK_PATH)
    assert report.cases
    for case in report.cases:
        with pytest.raises(ValueError, match="can never be presented"):
            to_verified_finding(case)
        display = case.as_public_display()
        assert display["is_synthetic"] is True
        assert display["is_real_verified_finding"] is False
        assert "SYNTHETIC" in display["display_label"]
