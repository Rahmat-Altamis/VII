"""Media-origin assessment from real metadata/provenance only. No fake AI detector."""
from __future__ import annotations

from vii.domain.schemas import MediaOrigin


def assess_origin(metadata: dict, acquisition: str, converted: bool) -> MediaOrigin:
    prov = [f"acquisition: {acquisition}"]
    if converted:
        prov.append("derived MP4 copy submitted to Meta; original preserved with separate SHA-256")
    notes = (f"Container={metadata.get('format','?')}, duration={metadata.get('duration_s',0):.1f}s, "
             f"video={metadata.get('video_codec','?')}, audio={metadata.get('audio_codec','?')}. "
             "No synthetic-media detector was run; origin claims require provenance records.")
    return MediaOrigin(notes=notes, metadata_summary=metadata, provenance=prov)
