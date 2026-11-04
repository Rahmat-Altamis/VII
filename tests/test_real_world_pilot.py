"""Real-world pilot dataset consistency (skips when dataset not built)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PILOT = (Path(__file__).resolve().parent.parent
         / "data" / "evaluation" / "real_world_pilot")

pytestmark = pytest.mark.skipif(
    not (PILOT / "videos.jsonl").exists(), reason="pilot dataset not built")


def test_manifest_matches_frame_ledgers():
    videos = [json.loads(ln)
              for ln in (PILOT / "videos.jsonl").read_text().splitlines()]
    assert len(videos) == 14
    for v in videos:
        index = PILOT / "frames" / v["video_id"] / "frame_index.jsonl"
        lines = index.read_text().splitlines()
        assert len(lines) == v["frames_in_window"] == v["decoded_frame_count"]
        first = json.loads(lines[0])
        assert first["frame_index"] == 0
        assert (PILOT / "annotations" / f"{v['video_id']}.json").exists()
        assert len(v["sha256"]) == 64


def test_coverage_never_claims_provider_analysis():
    coverage = json.loads((PILOT / "runs" / "coverage.json").read_text())
    assert len(coverage) == 14
    for c in coverage:
        assert c["frames_submitted_to_provider"] == 0
        assert c["frames_analyzed_by_provider"] == 0
        assert c["status"] == "blocked"
        assert c["frames_decoded"] > 0
