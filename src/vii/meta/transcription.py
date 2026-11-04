"""Audio transcription: FFmpeg extraction + Muse Voice Transcribe.

Documented contract (dev.meta.ai/docs/speech-to-text): RIFF/WAVE mono
16-bit PCM at 16 or 24 kHz to ``POST {base}/asr/transcribe`` (base
already includes ``/v1``), multipart ``request`` + ``audio``. Response
carries turn-level timing only, never word-level, never confidence.
DIARIZATION is the default mode because VII segments keep speaker
attribution, which ENDPOINTING drops and PUSH_TO_TALK drops turns for.

Without a live provider client, transcription is explicitly unavailable
(empty segments, engine="transcription-unavailable"), never fabricated.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from vii.domain.schemas import Transcript, TranscriptSegment

if TYPE_CHECKING:
    from vii.config import Settings
    from vii.meta.client import MetaClient

MAX_AUDIO_S = 600.0  # documented: audio must not exceed 10 minutes
MAX_BODY_BYTES = 32 * 1024 * 1024  # documented: request body cap
CHUNK_S = 540.0  # 9-minute chunks stay under both documented caps
WINDOW_S = 300.0  # VII evaluation window [0, min(duration, 300s))


def parse_asr_response(raw: dict, offset_s: float = 0.0) -> TranscriptSegment | list:
    """Map one ASR JSON body to VII segments (turn-level timing only).

    Returns the list of segments; empty transcript with no turns yields
    []. Offsets preserve timeline alignment for chunked audio.
    """
    segments: list[TranscriptSegment] = []
    for turn in (raw.get("turns") or []):
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("transcript", "") or "").strip()
        if not text:
            continue
        try:
            start = float(turn.get("startMs", 0) or 0) / 1000.0 + offset_s
            end = float(turn.get("endMs", 0) or 0) / 1000.0 + offset_s
        except (TypeError, ValueError):
            start, end = offset_s, offset_s
        segments.append(TranscriptSegment(
            start_s=start, end_s=end, text=text,
            speaker=(str(turn.get("speaker") or "") or None)))
    complete = str(raw.get("transcript", "") or raw.get("text", "") or "").strip()
    if not segments and complete:
        dur_ms = raw.get("audioDurationMs", 0) or 0
        try:
            dur = float(dur_ms) / 1000.0
        except (TypeError, ValueError):
            dur = 0.0
        segments = [TranscriptSegment(start_s=offset_s, end_s=offset_s + dur,
                                      text=complete)]
    return segments


def transcribe_audio(media_path: str | Path, settings: Settings,
                     client: MetaClient | None = None,
                     language: str | None = None) -> Transcript:
    from vii.media import ffmpeg as ffmpeg_mod

    tmp = Path(settings.storage_dir) / "tmp" / f"{Path(media_path).stem}_audio.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    offline = client is None or not client.live
    # Probe first: a video with no audio stream is an explicit state,
    # never reported as a successful transcription.
    try:
        meta = ffmpeg_mod.metadata_summary(
            ffmpeg_mod.probe(media_path, settings.ffprobe_bin))
    except Exception:
        return Transcript(segments=[], engine="ffmpeg-error",
                          language=language or "unknown", offline=True)
    if not meta.get("has_audio"):
        return Transcript(segments=[], engine="no-audio-stream",
                          language=language or "unknown", offline=False)
    duration = float(meta.get("duration_s") or 0)
    window_end = min(duration, WINDOW_S) if duration else WINDOW_S
    if offline:
        return Transcript(segments=[], engine="transcription-unavailable", offline=True,
                          language=language or "unknown")
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < window_end:
        chunks.append((start, min(start + CHUNK_S, window_end)))
        start += CHUNK_S
    all_segments: list[TranscriptSegment] = []
    session_ids: list[str] = []
    try:
        for i, (cstart, cend) in enumerate(chunks):
            wav = tmp.with_name(f"{tmp.stem}_c{i}.wav")
            try:
                ffmpeg_mod.extract_audio_wav(
                    media_path, wav, settings.ffmpeg_bin,
                    sample_rate=24000, start_s=cstart, end_s=cend)
            except Exception:
                return Transcript(segments=[], engine="ffmpeg-error",
                                  language=language or "unknown", offline=True)
            if wav.stat().st_size > MAX_BODY_BYTES:
                return Transcript(segments=[], engine="transcription-audio-too-large",
                                  language=language or "unknown", offline=False)
            if (cend - cstart) > MAX_AUDIO_S:
                return Transcript(segments=[], engine="transcription-audio-too-large",
                                  language=language or "unknown", offline=False)
            try:
                raw = client.transcribe(str(wav), language=language)
            except Exception as e:
                from vii.errors import UnsupportedCapabilityError
                if isinstance(e, UnsupportedCapabilityError):
                    return Transcript(segments=[],
                                      engine="transcription-unsupported",
                                      language=language or "unknown",
                                      offline=False)
                return Transcript(
                    segments=[], engine=f"transcribe-error: {str(e)[:200]}",
                    language=language or "unknown", offline=False)
            if not isinstance(raw, dict):
                return Transcript(segments=[], engine="transcribe-error: bad response",
                                  language=language or "unknown", offline=False)
            all_segments.extend(parse_asr_response(raw, offset_s=cstart))
            if raw.get("sessionId"):
                session_ids.append(str(raw["sessionId"]))
    finally:
        for wav in [tmp, *[tmp.with_name(f"{tmp.stem}_c{i}.wav")
                           for i in range(len(chunks))]]:
            try:
                wav.unlink(missing_ok=True)
            except Exception:
                pass
    tr = Transcript(segments=all_segments, language=language or "unknown",
                    engine=settings.meta_transcription_model, offline=False)
    tr.__dict__["_asr_session_ids"] = session_ids
    return tr
