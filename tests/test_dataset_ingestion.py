"""Dataset CSV subsystem: schema, row errors, duplicates, dry-run vs apply.

Synthetic CSV fixtures only — no video content, no model calls, and
ingestion must never create analyses.
"""
from __future__ import annotations


def _write(tmp_path, text: str, name: str = "dataset.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_file_is_normal_state(tmp_path):
    from vii.dataset.ingestion import validate_csv

    report = validate_csv(tmp_path / "does-not-exist.csv")
    assert report.exists is False
    assert report.ok is False  # nothing to ingest, but not an error state
    assert report.errors == []  # absence is a warning, never an exception


def test_valid_csv_parses_rows(tmp_path):
    from vii.dataset.ingestion import validate_csv

    csv_path = _write(tmp_path, (
        "video_id,source_url,platform,storage_ref,sha256,duration_s,title\n"
        "v001,https://example.com/a.mp4,generic,,"
        + "a" * 64 + ",12.5,First clip\n"
        "v002,,instagram,,,,\n"
    ))
    report = validate_csv(csv_path)
    assert report.ok and report.valid_rows == 2
    assert report.rows[0].video_id == "v001"
    assert report.rows[0].duration_s == 12.5
    assert report.rows[1].video_id == "v002"


def test_missing_required_column_is_header_error(tmp_path):
    from vii.dataset.ingestion import validate_csv

    report = validate_csv(_write(tmp_path, "source_url\nhttps://example.com/a.mp4\n"))
    assert not report.ok
    assert any("video_id" in e.message for e in report.errors)


def test_row_errors_are_reported_with_line_numbers(tmp_path):
    from vii.dataset.ingestion import validate_csv

    csv_path = _write(tmp_path, (
        "video_id,source_url,sha256,duration_s\n"
        ",https://example.com/a.mp4,,\n"
        "v002,ftp://example.com/b.mp4,,\n"
        "v003,https://example.com/c.mp4,not-hex,\n"
        "v004,https://example.com/d.mp4,,-5\n"
    ))
    report = validate_csv(csv_path)
    assert not report.ok
    lines = {e.line for e in report.errors}
    assert lines == {2, 3, 4, 5}
    assert report.valid_rows == 0


def test_duplicate_video_id_detected(tmp_path):
    from vii.dataset.ingestion import validate_csv

    csv_path = _write(tmp_path, "video_id\nv001\nv001\n")
    report = validate_csv(csv_path)
    assert not report.ok
    assert report.duplicate_video_ids == ["v001"]


def test_unknown_column_warns_but_does_not_fail(tmp_path):
    from vii.dataset.ingestion import validate_csv

    report = validate_csv(_write(tmp_path, "video_id,notes\nv001,hello\n"))
    assert report.ok
    assert any("notes" in w for w in report.warnings)


def test_dry_run_writes_nothing_and_apply_is_idempotent(tmp_path):
    from vii.dataset.ingestion import ingest_csv
    from vii.persistence.db import init_db
    from vii.persistence.repositories import DatasetRepo

    csv_path = _write(tmp_path, "video_id,source_url\nv001,https://example.com/a.mp4\n")
    factory = init_db(f"sqlite:///{tmp_path}/vii.db", tmp_path)

    dry = ingest_csv(csv_path, factory, "default", dry_run=True)
    assert dry.report.ok and dry.registered == 0
    with factory() as db:
        assert DatasetRepo(db).search("default", "", 20) == []

    applied = ingest_csv(csv_path, factory, "default", dry_run=False)
    assert applied.registered == 1
    again = ingest_csv(csv_path, factory, "default", dry_run=False)
    assert again.registered == 0 and again.skipped_duplicates == 1

    with factory() as db:
        row = DatasetRepo(db).get_by_consumer_video("default", "v001")
        assert row is not None
        assert row.annotation_status == "pending"
        # Consumer isolation: another consumer sees nothing.
        assert DatasetRepo(db).get_by_consumer_video("other", "v001") is None
