"""Authorized platform media acquisition (Instagram Graph, Facebook Page).

No unofficial downloaders. Each function returns a dict:
  {ok, media_url, media_id, platform, auth_method, status, error, ...}
Only official API media_url values are ever used; page permalinks are
never treated as direct video URLs.

Callers: application/pipeline.py _ingest (PUBLIC_URL branch), api/v1.py
(platform endpoints), sdk (indirectly). No existing module serves this.
"""
from __future__ import annotations


def _redact_params(params: dict) -> dict:
    return {k: ("***" if "token" in k.lower() or "secret" in k.lower() else v)
            for k, v in params.items()}
