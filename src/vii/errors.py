"""Typed VII errors: configuration vs provider vs unsupported capability.

Callers (API, worker, UI) can distinguish *why* an analysis failed without
string-matching exception messages. ProviderError subclasses RuntimeError so
existing ``except RuntimeError`` handlers keep working.
"""
from __future__ import annotations


class VIIError(Exception):
    """Base for all typed VII errors."""


class ProviderConfigurationError(VIIError, ValueError):
    """Provider-backed analysis was requested without valid configuration
    (e.g. no API key). Never recoverable by substituting fixtures."""


class ProviderError(VIIError, RuntimeError):
    """The provider request itself failed (network, auth, rate limit,
    malformed response). The analysis must be marked failed, not completed."""


class UnsupportedCapabilityError(VIIError, RuntimeError):
    """A requested feature is not available for this input/provider."""
