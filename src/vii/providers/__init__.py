"""Legacy provider interface (compatibility).

Active code should use vii.meta (client/video/search/transcription/parser),
vii.evidence and vii.verification directly. This package preserves the older
Provider / describe / extract / search / verify interface on top of the active
implementation:

- MockProvider: synthetic deterministic fixtures, explicit opt-in only via
  get_provider("mock"), never a default or a fallback for a missing key.
- MetaProvider: delegates to vii.meta.client.MetaClient (Responses API at
  META_BASE_URL). The old api.llama.com/compat/v1 chat-completions path was
  removed, it is not the documented Muse Spark endpoint and duplicated the
  client. Exactly one Meta transport exists: vii.meta.client.
"""
from __future__ import annotations

from vii.providers.base import (
    ClaimVerdict,
    ExtractedClaim,
    Provider,
    RetrievedSource,
    UnderstandingResult,
    parse_json_block,
)
from vii.providers.mock import MockProvider

__all__ = [
    "ClaimVerdict",
    "ExtractedClaim",
    "MockProvider",
    "Provider",
    "RetrievedSource",
    "UnderstandingResult",
    "get_provider",
    "parse_json_block",
]


def get_provider(name: str, **kwargs):
    """Return the 'mock' or 'meta' provider (lazy meta import keeps mock runs light)."""
    if name == "mock":
        return MockProvider(**kwargs)
    if name == "meta":
        from vii.providers.meta import MetaProvider

        return MetaProvider(**kwargs)
    raise ValueError(f"unknown provider: {name}")
