"""Bug 5 regression: /content/compare must measure perceptual distance
from the persisted ``phashes`` lists, never from corpus record names
(``phash_matches[*].record`` like "known1" is not a hash).

Local fixtures only — no provider calls, no network.
"""
from __future__ import annotations


def _job_with_report(settings, sha: str, phashes: list[str]) -> str:
    from vii.application.services import AnalysisService
    from vii.domain.schemas import AnalysisCreate
    from vii.persistence.repositories import AnalysisRepo

    svc = AnalysisService(settings)
    jid = svc.create(AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/demo.mp4"},
        offline=True))
    payload = {"dimensions": {"originality": {
        "sha256": sha, "exact_duplicate_of": None,
        "phash_matches": [{"record": "known1", "distance": 0}],
        "phashes": phashes, "notes": "fixture"}}}
    with svc.Session() as db:
        AnalysisRepo(db).add_report(jid, "json", "fixture.json", payload)
    return svc, jid


def test_compare_uses_phashes_not_record_names(settings, monkeypatch):
    import vii.api.v1 as v1
    from vii.domain.schemas import CompareRequest

    svc, ref = _job_with_report(
        settings, "a" * 64, ["8000000000000000"])
    _, cand = _job_with_report(
        settings, "b" * 64, ["8000000000000000"])
    monkeypatch.setattr(v1, "_service", svc)
    try:
        out = v1.compare(CompareRequest(
            reference_job_id=ref, candidate_job_id=cand), auth="default")
    finally:
        monkeypatch.setattr(v1, "_service", None)
    assert out["exact_match"] is False  # different stored SHA-256
    # Identical perceptual hashes -> distance 0. The old record-name bug
    # fed "known1" to phash_distance and always produced phash=None.
    assert out["phash"] == {"min_distance": 0, "comparisons": 1}
