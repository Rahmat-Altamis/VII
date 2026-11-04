"""VideoChecker: high-level library wrapper with SHA-256 result caching.

Checking the same local file twice never re-bills the provider: the
first report is stored under ``<storage_dir>/checker_cache/`` keyed by
the file's SHA-256 (URL sources are keyed by a hash of the URL) and
later checks return the stored report. Follow-up questions are answered
from the stored report only, they never call a provider.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vii.client import VII
from vii.config import Settings

_STATUSES = ("supported", "contradicted", "mixed_evidence",
             "insufficient_evidence", "unverifiable", "not_yet_analyzed")


def answer_question(report: dict, question: str) -> str:
    """Answer a follow-up from a stored report dict (no provider call)."""
    q = (question or "").strip().lower()
    claims = report.get("claims") or []
    if not q or q in ("claims", "list claims", "show claims"):
        if not claims:
            return "The stored report contains no claims."
        return "\n".join(
            f"[{c.get('status', '?')}] {c.get('text', '')}" for c in claims)
    for status in _STATUSES:
        if status in q or (status == "mixed_evidence" and "mixed" in q):
            matched = [c for c in claims if c.get("status") == status]
            if not matched:
                return f"No claims with status {status} in the stored report."
            return "\n".join(
                f"[{c.get('status')}] {c.get('text', '')}, "
                f"{c.get('explanation', '')}" for c in matched)
    if "source" in q or "evidence" in q:
        sources = report.get("sources") or []
        if not sources:
            return "The stored report contains no sources."
        return "\n".join(
            f"{s.get('url', '')} ({s.get('relationship') or 'context'})"
            for s in sources)
    words = [w for w in q.split() if len(w) > 3]
    matched = [c for c in claims
               if any(w in str(c.get("text", "")).lower()
                      or w in str(c.get("explanation", "")).lower()
                      for w in words)]
    if matched:
        return "\n".join(
            f"[{c.get('status', '?')}] {c.get('text', '')}, "
            f"{c.get('explanation', '')}" for c in matched)
    return ("No matching information in the stored report. "
            "Try 'claims', 'sources', or a claim status such as 'supported'.")


class VideoChecker:
    """Check videos through the VII pipeline, caching by SHA-256."""

    def __init__(self, api_key: str | None = None, *,
                 settings: Settings | None = None,
                 cache_dir: str | Path | None = None) -> None:
        self._client = VII(api_key=api_key, settings=settings)
        self.settings = self._client.settings
        self._cache_dir = (Path(cache_dir) if cache_dir is not None
                           else Path(self.settings.storage_dir)
                           / "checker_cache")

    def _cache_path(self, source: str) -> Path:
        p = Path(source)
        if not source.startswith(("http://", "https://")) and p.is_file():
            key = self._client.sha256(p)
            return self._cache_dir / f"{key}.json"
        digest = hashlib.sha256(source.encode()).hexdigest()
        return self._cache_dir / f"url-{digest}.json"

    def check(self, source: str | Path, *, title: str | None = None,
              demo: bool = False) -> dict[str, Any]:
        """Return the report for ``source``, from cache when available."""
        text = str(source)
        cache_path = self._cache_path(text)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass  # corrupt cache entry: recompute below
        report = self._client.analyze(text, title=title, demo=demo)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(report, indent=2, default=str))
        except OSError:
            pass  # caching is best-effort; the report is still returned
        return report

    def quick_look(self, source: str | Path) -> dict:
        """Fast local pre-screen (see :meth:`VII.quick_look`)."""
        return self._client.quick_look(source)

    def follow_up(self, report: dict, question: str) -> str:
        """Answer ``question`` from a stored report. Never calls a provider."""
        return answer_question(report, question)

    def close(self) -> None:
        self._client.close()
