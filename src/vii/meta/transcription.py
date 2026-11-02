"""Audio transcription: FFmpeg extraction + Muse Voice Transcribe.

Without a live provider client, transcription is explicitly unavailable
(empty segments, engine="transcription-unavailable") — never fabricated."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from vii.domain.schemas import Transcript, TranscriptSegment

if TYPE_CHECKING:
    from vii.config import Settings
    from vii.meta.client import MetaClient


def transcribe_audio(media_path: str | Path, settings: "Settings",
                     client: "MetaClient | None" = None,
                     language: str | None = None) -> Transcript:
    from vii.media import ffmpeg as ffmpeg_mod
    tmp = Path(settings.storage_dir) / "tmp" / f"{Path(media_path).stem}_audio.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    offline = client is None or not client.live
    try:
        audio = ffmpeg_mod.extract_audio(media_path, tmp, settings.ffmpeg_bin)
    except Exception as e:
        return Transcript(segments=[], engine="ffmpeg-error",
                          language=language or "unknown", offline=True)
    if offline:
        return Transcript(segments=[], engine="transcription-unavailable", offline=True,
                          language=language or "unknown")
    try:
        raw = client.transcribe(str(audio), language=language)
    except Exception as e:
        return Transcript(segments=[], engine=f"transcribe-error: {str(e)[:200]}",
                          language=language or "unknown", offline=False)
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
    segments: list[TranscriptSegment] = []
    text = raw.get("text", "") if isinstance(raw, dict) else ""
    for seg in (raw.get("segments", []) if isinstance(raw, dict) else []):
        try:
            segments.append(TranscriptSegment(
                start_s=float(seg.get("start", 0)), end_s=float(seg.get("end", 0)),
                text=str(seg.get("text", "")), speaker=seg.get("speaker")))
        except Exception:
            continue
    if not segments and text:
        segments = [TranscriptSegment(start_s=0.0, end_s=0.0, text=text)]
    lang = (raw.get("language") if isinstance(raw, dict) else None) or language or "unknown"
    return Transcript(segments=segments, language=lang,
                      engine=settings.meta_transcription_model, offline=False)
