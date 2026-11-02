"""Originality: SHA-256 exact match + perceptual-hash near-duplicate search."""
from __future__ import annotations

from pathlib import Path

from vii.domain.schemas import OriginalityResult
from vii.media.hashing import phash_distance, phash_frames, sha256_file


def assess_originality(media_path: str | Path, corpus_dir: str | Path | None,
                       sample_frames: list[Path] | None = None) -> OriginalityResult:
    s = str(media_path)
    if s.startswith(("http://", "https://")) or not Path(s).is_file():
        return OriginalityResult(
            sha256="", exact_duplicate_of=None, phash_matches=[],
            notes="Original media not stored locally (remote URL); exact/near-duplicate "
                  "comparison requires a local file.")
    # sha256_file is imported at module top. The previous revision referenced an
    # undefined `digest` name in the corpus loop and return statement below,
    # crashing every local-file run at this stage with NameError.
    digest = sha256_file(media_path)
    exact = None
    matches: list[dict] = []
    hashes = phash_frames(sample_frames or [])
    if corpus_dir and Path(corpus_dir).exists():
        import json as _json
        for rec in Path(corpus_dir).glob("*.json"):
            try:
                data = _json.loads(rec.read_text())
            except Exception:
                continue
            if data.get("sha256") == digest:
                exact = rec.stem
            for h in hashes:
                for ch in data.get("phashes", []):
                    d = phash_distance(h, ch)
                    if d is not None and d <= 8:
                        matches.append({"record": rec.stem, "distance": d})
                        break
    notes = ("Exact duplicate found." if exact else
             f"{len(matches)} near-duplicate frame(s) in corpus." if matches else
             "No exact or near duplicates in the local comparison corpus.")
    return OriginalityResult(sha256=digest, exact_duplicate_of=exact,
                             phash_matches=matches[:20], notes=notes)
