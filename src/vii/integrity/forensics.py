"""Manipulation forensics: local signal ensemble, never a fake verdict.

This is VII's deepfake/manipulation surface. It evaluates weak local
proxies over sampled frames and provenance metadata:

- ``frame_reuse``, a sampled frame that reappears (near-identical
  perceptual hash) at a non-consecutive position, consistent with
  looped or re-inserted segments;
- ``recompression_error``, error-level-style analysis: frames are
  re-encoded as JPEG and the mean absolute error is measured. Elevated
  error can indicate compositing or repeated re-encoding, but every
  platform re-encode raises it too;
- ``temporal_transitions``, share of abrupt perceptual transitions
  between consecutive sampled frames (heavy editing and ordinary scene
  cuts both fire this);
- ``provenance_metadata``, whether container/codec metadata survived;
  platforms strip it from genuine media routinely.

The aggregated status is categorical (``signals_detected`` /
``no_signals_detected`` / ``unavailable``). There is deliberately no
probability and no genuine/fake verdict: these signals cannot prove
manipulation or authenticity, and no synthetic-media classifier is run.
"""
from __future__ import annotations

from pathlib import Path

from vii.domain.schemas import DeepfakeAssessment, ForensicSignal
from vii.media.hashing import phash_distance, phash_frames

_ELA_SIGNAL_THRESHOLD = 12.0  # mean abs JPEG re-encode error (0-255 scale)
_ABRUPT_PHASH_DISTANCE = 25   # hamming distance treated as abrupt change
_REUSE_PHASH_DISTANCE = 2     # hamming distance treated as same frame


def assess_manipulation(media_path: str | Path,
                        sample_frames: list[Path] | None = None,
                        metadata: dict | None = None) -> DeepfakeAssessment:
    """Evaluate manipulation-forensics signals for a local media file.

    Never raises: anything that cannot be evaluated is reported as
    ``unavailable`` signals or an ``unavailable`` overall status. Remote
    URLs are not fetched.
    """
    s = str(media_path)
    if s.startswith(("http://", "https://")) or not Path(s).is_file():
        return DeepfakeAssessment(
            status="unavailable",
            signals=[ForensicSignal(
                name="local_media", status="unavailable",
                detail="Manipulation forensics require a local media "
                       "file; remote media was not fetched.")])
    frames = [Path(f) for f in (sample_frames or []) if Path(f).is_file()]
    signals = [
        _frame_reuse_signal(frames),
        _recompression_signal(frames),
        _temporal_signal(frames),
        _provenance_signal(metadata),
    ]
    evaluated = [sig for sig in signals if sig.status != "unavailable"]
    if not evaluated:
        status = "unavailable"
    elif any(sig.status == "signal" for sig in evaluated):
        status = "signals_detected"
    else:
        status = "no_signals_detected"
    return DeepfakeAssessment(status=status, signals=signals)


def _hashes(frames: list[Path]) -> list[str]:
    if len(frames) < 2:
        return []
    return phash_frames(frames)


def _frame_reuse_signal(frames: list[Path]) -> ForensicSignal:
    hashes = _hashes(frames)
    if len(hashes) < 3:
        return ForensicSignal(
            name="frame_reuse", status="unavailable",
            detail="Frame-reuse check needs at least 3 readable sampled "
                   "frames with perceptual hashes.")
    pairs = []
    for i, h in enumerate(hashes):
        for j in range(i + 2, len(hashes)):
            d = phash_distance(h, hashes[j])
            if d is not None and d <= _REUSE_PHASH_DISTANCE:
                pairs.append((i, j, d))
    if pairs:
        i, j, d = pairs[0]
        return ForensicSignal(
            name="frame_reuse", status="signal", value=float(d),
            detail=(f"Sampled frame {i} reappears at position {j} "
                    f"(perceptual-hash distance {d}); consistent with a "
                    "looped or re-inserted segment. Reused intros, "
                    "slates, and static shots fire this on genuine media."))
    return ForensicSignal(
        name="frame_reuse", status="no_signal",
        detail="No non-consecutive sampled frame is a near-duplicate "
               "of another.")


def _recompression_signal(frames: list[Path]) -> ForensicSignal:
    if not frames:
        return ForensicSignal(
            name="recompression_error", status="unavailable",
            detail="No sampled frames available for recompression "
                   "analysis.")
    try:
        import io

        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="recompression_error", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    errors: list[float] = []
    for frame in frames[:3]:
        try:
            with Image.open(frame) as im:
                gray = im.convert("L").resize((64, 64))
                buf = io.BytesIO()
                gray.save(buf, "JPEG", quality=90)
                buf.seek(0)
                with Image.open(buf) as reenc:
                    reenc.load()
                    # Pillow 13+: get_flattened_data replaces deprecated getdata.
                    gray_data = (gray.get_flattened_data()
                                 if hasattr(gray, "get_flattened_data")
                                 else gray.getdata())
                    reenc_gray = reenc.convert("L").resize((64, 64))
                    reenc_data = (reenc_gray.get_flattened_data()
                                   if hasattr(reenc_gray, "get_flattened_data")
                                   else reenc_gray.getdata())
                    a = list(gray_data)
                    b = list(reenc_data)
            errors.append(sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a))
        except Exception:
            continue
    if not errors:
        return ForensicSignal(
            name="recompression_error", status="unavailable",
            detail="Sampled frames could not be decoded for "
                   "recompression analysis.")
    value = sum(errors) / len(errors)
    if value > _ELA_SIGNAL_THRESHOLD:
        return ForensicSignal(
            name="recompression_error", status="signal", value=value,
            detail=(f"Mean JPEG re-encode error {value:.1f} exceeds "
                    f"{_ELA_SIGNAL_THRESHOLD:.0f}; consistent with "
                    "compositing or repeated re-encoding. Platform "
                    "re-encodes fire this on genuine media, weak proxy "
                    "only."))
    return ForensicSignal(
        name="recompression_error", status="no_signal", value=value,
        detail=f"Mean JPEG re-encode error {value:.1f} within normal "
               "range for sampled frames.")


def _temporal_signal(frames: list[Path]) -> ForensicSignal:
    hashes = _hashes(frames)
    if len(hashes) < 2:
        return ForensicSignal(
            name="temporal_transitions", status="unavailable",
            detail="Temporal-transition check needs at least 2 sampled "
                   "frames with perceptual hashes.")
    distances = [d for a, b in zip(hashes, hashes[1:], strict=False)
                 if (d := phash_distance(a, b)) is not None]
    if not distances:
        return ForensicSignal(
            name="temporal_transitions", status="unavailable",
            detail="Perceptual hashes could not be compared.")
    abrupt = sum(1 for d in distances if d > _ABRUPT_PHASH_DISTANCE)
    ratio = abrupt / len(distances)
    if ratio > 0.5:
        return ForensicSignal(
            name="temporal_transitions", status="signal", value=ratio,
            detail=(f"{abrupt}/{len(distances)} sampled transitions are "
                    "abrupt; consistent with heavy editing or frequent "
                    "scene cuts. Cuts alone are not manipulation "
                    "evidence."))
    return ForensicSignal(
        name="temporal_transitions", status="no_signal", value=ratio,
        detail=f"{abrupt}/{len(distances)} sampled transitions are "
               "abrupt, within normal editorial range.")


def _provenance_signal(metadata: dict | None) -> ForensicSignal:
    meta = metadata or {}
    known = [k for k in ("format", "video_codec", "audio_codec")
             if meta.get(k)]
    if not known:
        return ForensicSignal(
            name="provenance_metadata", status="signal",
            detail=("No container/codec metadata available; provenance "
                    "is sparse. Platforms strip metadata from genuine "
                    "media routinely, this is not manipulation "
                    "evidence on its own."))
    return ForensicSignal(
        name="provenance_metadata", status="no_signal",
        detail="Container metadata present: "
               + ", ".join(f"{k}={meta[k]}" for k in known) + ".")
