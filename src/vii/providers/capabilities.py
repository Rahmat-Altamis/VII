"""Provider capability report — local configuration only, no provider calls.

Every state is explicit: ``configured_unverified`` means credentials/config
are present but the live contract has not been exercised in this
environment; ``blocked`` means a required contract or credential is
missing; ``disabled`` means the stage is turned off. Nothing here contacts
a provider or spends credits.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vii.config import Settings


def provider_capabilities(settings: Settings) -> dict:
    """Return per-capability readiness for diagnostics/readiness endpoints."""
    from vii.providers.visual import get_visual_perception_provider

    visual = get_visual_perception_provider(settings).capabilities()
    return {
        "video_understanding": {
            "status": ("configured_unverified" if settings.live_mode
                       else "demo_opt_in" if settings.demo_enabled
                       else "blocked"),
            "provider": "meta",
            "model": settings.meta_model,
            "base_url": settings.meta_base_url,
            "native_video": "implemented_in_adapter_unverified_live",
            "notes": ("Configured model identifier and input_video/file_id "
                      "payloads are implemented in vii.meta; live acceptance, "
                      "format/size limits, and pricing are not verified "
                      "against official documentation in this environment."),
        },
        "transcription": {
            "status": ("disabled" if not settings.enable_transcription
                       else "configured_unverified" if settings.live_mode
                       else "blocked"),
            "model": settings.meta_transcription_model,
            "notes": ("Separate audio path (FFmpeg extraction + transcription "
                      "model); runs only when enabled and a local file is "
                      "available. Disable when the native video path already "
                      "covers the audio needed."),
        },
        "evidence_search": {
            "status": ("configured_unverified" if settings.live_mode
                       else "unavailable_no_provider"),
            "method": "meta_web_search",
            "notes": ("Retrieval is separate from visual interpretation; "
                      "without a live provider no search is performed and no "
                      "sources are fabricated."),
        },
        "visual_perception": {
            "status": visual["status"],
            "provider": settings.visual_perception_provider or "none",
            "model": settings.sam_model or "sam-3.1",
            "supports_tracking": visual["supports_tracking"],
            "notes": visual["notes"],
        },
        "ffmpeg": {
            "status": "optional",
            "notes": ("Required only for non-MP4 conversion, optional audio "
                      "extraction, and frame sampling. Supported native MP4 "
                      "ingestion validates without it."),
        },
    }
