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
    malformed response). The analysis must be marked failed, not completed.

    ``retryable`` tells the worker whether re-running the whole job could
    plausibly succeed; the provider client already retries transient
    transport errors internally, so worker-level retries are opt-in.
    """

    retryable = False


class ProviderPermissionError(ProviderError):
    """Provider rejected the credentials/permissions (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """Provider rate-limited the request (HTTP 429)."""

    retryable = True


class ProviderTimeoutError(ProviderError):
    """Provider request timed out."""

    retryable = True


class MalformedProviderResponseError(ProviderError):
    """Provider returned data that could not be parsed or validated."""


class UnsupportedCapabilityError(VIIError, RuntimeError):
    """A requested feature is not available for this input/provider."""


# -- Media ingestion (provider-independent; ValueError base keeps the
# existing API ``ValueError -> 400`` mapping working) ----------------------

class InvalidUploadError(VIIError, ValueError):
    """The uploaded/local media is missing, unreadable, or malformed."""


class UnsupportedMediaError(VIIError, ValueError):
    """The media container/signature is not supported for this path."""


class UploadTooLargeError(VIIError, ValueError):
    """The media exceeds the configured upload-size limit."""


class MediaDurationExceededError(VIIError, ValueError):
    """The media duration exceeds the configured maximum."""
