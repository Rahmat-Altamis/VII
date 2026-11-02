"""Regression: assess_originality must not crash on local files.

Before the fix, `assess_originality` referenced an undefined `digest`
name in the corpus loop and return statement, raising NameError for
every local-file input (remote URLs returned early and hid the bug).
These tests use synthetic byte fixtures only — no video content.
"""
from __future__ import annotations

import hashlib
import json


def test_assess_originality_local_file_no_corpus_match(tmp_path):
    from vii.integrity.originality import assess_originality

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"synthetic-test-bytes-not-a-real-video")
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    result = assess_originality(media, corpus, [])

    expected = hashlib.sha256(b"synthetic-test-bytes-not-a-real-video").hexdigest()
    assert result.sha256 == expected
    assert result.exact_duplicate_of is None
    assert result.phash_matches == []


def test_assess_originality_exact_duplicate_detected(tmp_path):
    from vii.integrity.originality import assess_originality

    media = tmp_path / "clip.mp4"
    payload = b"another-synthetic-fixture"
    media.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "known1.json").write_text(json.dumps({"sha256": digest, "phashes": []}))

    result = assess_originality(media, corpus, [])

    assert result.sha256 == digest
    assert result.exact_duplicate_of == "known1"


def test_assess_originality_remote_url_still_short_circuits(tmp_path):
    from vii.integrity.originality import assess_originality

    result = assess_originality("https://example.com/clip.mp4", tmp_path, [])

    assert result.sha256 == ""
    assert result.exact_duplicate_of is None
