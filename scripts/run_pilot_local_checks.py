"""Local VII checks for the real-world pilot (no provider calls).

Per video: inspect_media (validation + SHA-256), originality vs the local
corpus, and manipulation-forensics signals. Results land in runs/. The
coverage ledger keeps decoded vs provider-analyzed frames separate:
provider analysis is blocked (not run), never claimed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vii import VII  # noqa: E402
from vii.config import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "evaluation" / "real_world_pilot"


def main() -> int:
    settings = Settings(_env_file=None, VII_API_HOST="127.0.0.1",
                        VII_DATABASE_URL=f"sqlite:///{ROOT}/data/vii.db",
                        VII_STORAGE_DIR=ROOT / "data")
    client = VII(settings=settings)
    videos = [json.loads(ln)
              for ln in (PILOT / "videos.jsonl").read_text().splitlines()]
    coverage = {c["video_id"]: c
                for c in json.loads((PILOT / "runs" / "coverage.json").read_text())}
    for v in videos:
        info = client.inspect_media(v["original_path"])
        orig = client.assess_originality(v["original_path"])
        forensic = client.assess_forensics(v["original_path"])
        result = {
            "video_id": v["video_id"],
            "inspect": info.model_dump(),
            "sha256_matches_manifest": info.sha256 == v["sha256"],
            "originality": orig.model_dump(),
            "forensics_status": forensic.status,
            "provider_analysis": "blocked_not_run",
        }
        (PILOT / "runs" / f"{v['video_id']}_local.json").write_text(
            json.dumps(result, indent=2, default=str))
        c = coverage[v["video_id"]]
        c["local_checks"] = "completed"
        print(f"{v['video_id']}: sha_ok={result['sha256_matches_manifest']} "
              f"forensics={forensic.status}", flush=True)
    (PILOT / "runs" / "coverage.json").write_text(
        json.dumps(list(coverage.values()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
