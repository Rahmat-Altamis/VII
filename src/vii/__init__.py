"""Video Integrity Intelligence — evidence-first video intelligence platform.

Supported public API for downstream applications and a future CLI.
Internal packages (``vii.api``, ``vii.application``, ``vii.persistence``,
``vii.meta``, ...) are implementation details and may change without
notice; import only the names exported here and the typed models and
errors listed in ``__all__``.
"""
from vii.client import VII
from vii.config import Settings, get_settings
from vii.domain.schemas import (
    AnalysisCreate,
    DeepfakeAssessment,
    MediaIngestionResult,
    OriginalityResult,
    ReportPayload,
    VideoSourceIn,
)
from vii.errors import (
    InvalidUploadError,
    MalformedProviderResponseError,
    MediaDurationExceededError,
    ProviderConfigurationError,
    ProviderError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    UnsupportedCapabilityError,
    UnsupportedMediaError,
    UploadTooLargeError,
    VIIError,
)

__version__ = "1.0.0"
__all__ = [
    "VII",
    "Settings",
    "get_settings",
    "__version__",
    # Typed input/output contracts
    "AnalysisCreate",
    "VideoSourceIn",
    "MediaIngestionResult",
    "OriginalityResult",
    "DeepfakeAssessment",
    "ReportPayload",
    # Predictable exception behavior
    "VIIError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderPermissionError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "MalformedProviderResponseError",
    "UnsupportedCapabilityError",
    "InvalidUploadError",
    "UnsupportedMediaError",
    "UploadTooLargeError",
    "MediaDurationExceededError",
]
