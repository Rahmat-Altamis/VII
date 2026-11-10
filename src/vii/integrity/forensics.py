"""Manipulation forensics: local signal ensemble, never a fake verdict.

This is VII's deepfake/manipulation surface. Single stills from modern
generators look real, so detection here is temporal (measured across
sampled frames, never one image) and forensic (pixel structure, not
content). It evaluates weak local proxies over sampled frames and
provenance metadata:

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
- ``reencode_layer`` (step 1 of 3: original vs re-encoded), elevated
  block-boundary gradients consistent with at least one re-encode
  generation — platform compression or a screen recording. A screen
  layer adds its own compression and re-encoding noise and washes out
  the original sensor fingerprint, so when this fires the three
  pixel-level signals below are discounted (``unavailable``) instead
  of trusted;
- ``sensor_noise`` (step 2: pixel tell), flat or unnaturally uniform
  sensor-noise residuals. Camera capture carries varying sensor noise;
  synthetic media tends toward flat lighting and uniform noise. Only
  evaluated when no re-encode layer was detected;
- ``light_bias`` (step 2: pixel tell), shadow/highlight noise ratio.
  Natural light gives shadows and highlights different noise levels;
  near-identical noise across luminance is flat uniform lighting.
  Only evaluated when no re-encode layer was detected;
- ``frequency_artifacts`` (step 2: pixel tell), narrow spectral
  concentration in block-DCT spectra. Camera noise spreads energy
  across the spectrum; synthetic periodic patterns (upsampling grids,
  overlaid structures) concentrate it into spikes. Only evaluated
  when no re-encode layer was detected, because quantization
  reshapes spectra too;
- ``temporal_flicker`` (step 2: motion tell), noise-level jumps
  between sampled frames. Stable camera noise varies little
  frame to frame; flicker and morphing-like instability shows as
  abrupt changes. Temporal behavior survives re-encoding, so this
  is evaluated even when a re-encode layer is present — but cuts,
  lighting changes, and scene motion fire it on genuine media;
- ``audio_tone`` (step 2: audio tell), room-tone floor in quiet
  passages of an extracted WAV. Natural audio keeps a low varying
  noise floor with breaths and ambience; studio/TTS-clean audio
  sits at digital silence. Needs a local audio track; evaluated
  even when a re-encode layer is present;
- ``provenance_metadata``, whether container/codec metadata survived;
  platforms strip it from genuine media routinely.

Step 3 (what is the claim?) is left to the reviewer: these signals
feed the report, they never answer it. The aggregated status is
categorical (``signals_detected`` / ``no_signals_detected`` /
``unavailable``). There is deliberately no probability and no
genuine/fake verdict: these signals cannot prove manipulation or
authenticity, and no synthetic-media classifier is run.
"""
from __future__ import annotations

import math
from pathlib import Path

from vii.domain.schemas import DeepfakeAssessment, ForensicSignal
from vii.media.hashing import phash_distance, phash_frames

_ELA_SIGNAL_THRESHOLD = 12.0  # mean abs JPEG re-encode error (0-255 scale)
_ABRUPT_PHASH_DISTANCE = 25   # hamming distance treated as abrupt change
_REUSE_PHASH_DISTANCE = 2     # hamming distance treated as same frame
_BLOCK_SIGNAL_RATIO = 1.3     # block-boundary/interior gradient ratio
_NOISE_FLAT_SD = 1.0          # residual std below this: flat, no sensor noise
_NOISE_UNIFORM_SPREAD = 0.2   # quadrant spread below this: uniform noise
_LIGHT_UNIFORM_RATIO = 0.85   # shadow/highlight noise ratio at/above: flat light
_PIXEL_FRAMES = 3             # pixel signals aggregate over at most N frames
_SPECTRAL_SIGNAL_CONC = 8.0   # spectral concentration at/above: periodic spike
_FLICKER_SIGNAL_COV = 0.4     # cross-frame noise CoV at/above: flicker
_FLICKER_FRAMES = 8           # flicker aggregates over at most N frames
_AUDIO_FLOOR_DB = -60.0       # room-tone floor below this: too clean
_AUDIO_WINDOW_S = 0.1         # room-tone measurement window

# Precomputed 8x8 DCT-II basis (pure stdlib; no numpy dependency).
_DCT_COS = [[math.cos((2 * x + 1) * u * math.pi / 16) for x in range(8)]
            for u in range(8)]
_DCT_ALPHA = [math.sqrt(1 / 8)] + [0.5] * 7


def assess_manipulation(media_path: str | Path,
                        sample_frames: list[Path] | None = None,
                        metadata: dict | None = None,
                        audio_path: str | Path | None = None) -> DeepfakeAssessment:
    """Evaluate manipulation-forensics signals for a local media file.

    Never raises: anything that cannot be evaluated is reported as
    ``unavailable`` signals or an ``unavailable`` overall status. Remote
    URLs are not fetched. ``audio_path`` is an optional local WAV for
    the room-tone signal; ``None`` leaves that signal unavailable.
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
    reencode = _reencode_signal(frames)
    if reencode.status == "signal":
        # Step 1 fired: a re-encode/screen layer washes out the original
        # sensor fingerprint and reshapes fine spectra, so pixel tells
        # are discounted, never trusted.
        pixel = [_pixel_discounted("sensor_noise"),
                 _pixel_discounted("light_bias"),
                 _pixel_discounted("frequency_artifacts")]
    else:
        pixel = [_noise_signal(frames), _light_signal(frames),
                 _frequency_signal(frames)]
    signals = [
        _frame_reuse_signal(frames),
        _recompression_signal(frames),
        _temporal_signal(frames),
        reencode,
        *pixel,
        _flicker_signal(frames),
        _audio_signal(audio_path, metadata),
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


def _flat_pixels(im) -> list[int]:
    data = (im.get_flattened_data() if hasattr(im, "get_flattened_data")
            else im.getdata())
    return list(data)


def _residuals(px: list[int], w: int, h: int) -> list[tuple[int, float]]:
    """Per-pixel (luminance, noise residual); borders skipped."""
    out = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            nb = (px[i - 1] + px[i + 1] + px[i - w] + px[i + w]) / 4.0
            out.append((px[i], px[i] - nb))
    return out


def _pixel_discounted(name: str) -> ForensicSignal:
    return ForensicSignal(
        name=name, status="unavailable",
        detail=("Discounted: a re-encode/screen layer was detected, which "
                "washes out sensor-noise fingerprints and reshapes fine "
                "spectra. No pixel-level conclusion can be drawn from "
                "these frames; weigh provenance and the claim instead."))


def _frame_noise_sd(gray) -> float:
    import statistics

    w, h = gray.size
    res = _residuals(_flat_pixels(gray), w, h)
    return statistics.pstdev(r for _, r in res)


def _spectral_concentration(gray) -> float | None:
    """Narrow-band spectral concentration over 8x8 block DCTs.

    Mean |coefficient| per position across blocks, band u+v>=4;
    returns max/mean (None when the band carries no energy, i.e.
    frames too flat to measure). Camera noise spreads energy
    (value ~1-2); periodic synthetic structure concentrates it.
    """
    w, h = gray.size
    px = _flat_pixels(gray)
    pos = [[0.0] * 8 for _ in range(8)]
    nblocks = 0
    for by in range(0, h - 7, 8):
        for bx in range(0, w - 7, 8):
            for u in range(8):
                for v in range(8):
                    s = 0.0
                    for x in range(8):
                        cu = _DCT_COS[u][x]
                        for y in range(8):
                            s += ((px[(by + y) * w + bx + x] - 128)
                                  * cu * _DCT_COS[v][y])
                    pos[u][v] += abs(_DCT_ALPHA[u] * _DCT_ALPHA[v] * s)
            nblocks += 1
    if not nblocks:
        return None
    band = [pos[u][v] / nblocks for u in range(8) for v in range(8)
            if u + v >= 4]
    total = sum(band)
    if total <= 1e-9:
        return None
    return max(band) / (total / len(band))


def _frequency_signal(frames: list[Path]) -> ForensicSignal:
    if not frames:
        return ForensicSignal(
            name="frequency_artifacts", status="unavailable",
            detail="No sampled frames available for spectral analysis.")
    try:
        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="frequency_artifacts", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    concs: list[float] = []
    for frame in frames[:_PIXEL_FRAMES]:
        try:
            with Image.open(frame) as im:
                gray = im.convert("L").resize((64, 64))
                conc = _spectral_concentration(gray)
        except Exception:
            continue
        if conc is not None:
            concs.append(conc)
    if not concs:
        return ForensicSignal(
            name="frequency_artifacts", status="unavailable",
            detail="Sampled frames too flat to measure spectral structure.")
    conc = sum(concs) / len(concs)
    n = len(concs)
    if conc >= _SPECTRAL_SIGNAL_CONC:
        return ForensicSignal(
            name="frequency_artifacts", status="signal", value=conc,
            detail=(f"Spectral concentration {conc:.1f} at or above "
                    f"{_SPECTRAL_SIGNAL_CONC:.0f} across {n} sampled "
                    "frame(s): energy bunches into narrow spectral spikes "
                    "instead of spreading like camera noise. Consistent "
                    "with synthetic periodic structure (upsampling grids, "
                    "overlaid patterns). Regular genuine textures "
                    "(fabrics, architecture, screens) fire this too. "
                    "Weak proxy only."))
    return ForensicSignal(
        name="frequency_artifacts", status="no_signal", value=conc,
        detail=(f"Spectral concentration {conc:.1f} within normal range "
                f"across {n} sampled frame(s); energy spreads across the "
                "spectrum like camera capture. Weak proxy only."))


def _flicker_signal(frames: list[Path]) -> ForensicSignal:
    import statistics

    if len(frames) < 3:
        return ForensicSignal(
            name="temporal_flicker", status="unavailable",
            detail="Flicker check needs at least 3 sampled frames.")
    try:
        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="temporal_flicker", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    sds: list[float] = []
    for frame in frames[:_FLICKER_FRAMES]:
        try:
            with Image.open(frame) as im:
                sds.append(_frame_noise_sd(im.convert("L").resize((64, 64))))
        except Exception:
            continue
    if len(sds) < 3:
        return ForensicSignal(
            name="temporal_flicker", status="unavailable",
            detail="Fewer than 3 sampled frames could be decoded for "
                   "flicker analysis.")
    mean = sum(sds) / len(sds)
    if mean <= 1e-9:
        return ForensicSignal(
            name="temporal_flicker", status="unavailable",
            detail="Sampled frames carry no measurable noise; flicker "
                   "cannot be assessed.")
    cov = statistics.pstdev(sds) / mean
    n = len(sds)
    if cov >= _FLICKER_SIGNAL_COV:
        return ForensicSignal(
            name="temporal_flicker", status="signal", value=cov,
            detail=(f"Noise level jumps between sampled frames (variation "
                    f"{cov:.2f} across {n} frames): flicker/morphing-like "
                    "instability. Evaluated even under a re-encode layer, "
                    "since temporal behavior survives compression — but "
                    "cuts, lighting changes, and scene motion fire this on "
                    "genuine edited media. Weak proxy only."))
    return ForensicSignal(
        name="temporal_flicker", status="no_signal", value=cov,
        detail=(f"Noise level stable across {n} sampled frames "
                f"(variation {cov:.2f}); no flicker measured. Weak proxy "
                "only."))


def _audio_signal(audio_path: str | Path | None,
                  metadata: dict | None) -> ForensicSignal:
    import statistics
    import struct
    import wave

    meta = metadata or {}
    if meta.get("has_audio") is False:
        return ForensicSignal(
            name="audio_tone", status="unavailable",
            detail="Video has no audio stream; room tone cannot be "
                   "measured.")
    if audio_path is None or not Path(audio_path).is_file():
        return ForensicSignal(
            name="audio_tone", status="unavailable",
            detail="No audio available for room-tone analysis.")
    try:
        with wave.open(str(audio_path), "rb") as wav:
            nchan, width, rate, nframes = (wav.getnchannels(),
                                           wav.getsampwidth(),
                                           wav.getframerate(),
                                           wav.getnframes())
            if wav.getcomptype() != "NONE" or width not in (1, 2):
                return ForensicSignal(
                    name="audio_tone", status="unavailable",
                    detail="Audio is not plain PCM 8/16-bit WAV; room tone "
                           "cannot be measured.")
            raw = wav.readframes(nframes)
    except Exception:
        return ForensicSignal(
            name="audio_tone", status="unavailable",
            detail="Audio could not be decoded for room-tone analysis.")
    if width == 1:
        samples = [b - 128 for b in raw]
        scale = 128.0
    else:
        vals = struct.unpack(f"<{len(raw) // 2}h", raw)
        if nchan > 1:
            samples = [sum(vals[i:i + nchan]) / nchan
                       for i in range(0, len(vals), nchan)]
        else:
            samples = list(vals)
        scale = 32768.0
    per = max(1, int(rate * _AUDIO_WINDOW_S))
    windows = [samples[i:i + per] for i in range(0, len(samples), per)]
    if len(windows) < 10:
        return ForensicSignal(
            name="audio_tone", status="unavailable",
            detail="Audio too short to measure a room-tone floor.")
    levels = []
    for window in windows:
        rms = math.sqrt(sum(s * s for s in window) / len(window)) / scale
        levels.append(20 * math.log10(rms) if rms > 0 else -96.0)
    if max(levels) - min(levels) < 3.0:
        return ForensicSignal(
            name="audio_tone", status="unavailable",
            detail="Audio has no quiet passages to measure room tone "
                   "against.")
    floor = statistics.median(sorted(levels)[:max(1, len(levels) // 10)])
    if floor < _AUDIO_FLOOR_DB:
        return ForensicSignal(
            name="audio_tone", status="signal", value=floor,
            detail=(f"Quiet passages sit at digital silence ({floor:.0f} "
                    "dBFS): no measurable room tone, breaths, or ambience. "
                    "Consistent with studio/TTS-clean audio. Gated or "
                    "denoised genuine audio fires this too. Weak proxy "
                    "only."))
    return ForensicSignal(
        name="audio_tone", status="no_signal", value=floor,
        detail=(f"Quiet passages carry a varying noise floor ({floor:.0f} "
                "dBFS): room tone present. Weak proxy only."))


def _noise_signal(frames: list[Path]) -> ForensicSignal:
    import statistics

    if not frames:
        return ForensicSignal(
            name="sensor_noise", status="unavailable",
            detail="No sampled frames available for sensor-noise analysis.")
    try:
        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="sensor_noise", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    sds: list[float] = []
    spreads: list[float] = []
    for frame in frames[:_PIXEL_FRAMES]:
        try:
            with Image.open(frame) as im:
                gray = im.convert("L").resize((64, 64))
                w, h = gray.size
                res = _residuals(_flat_pixels(gray), w, h)
        except Exception:
            continue
        vals = [r for _, r in res]
        sd = statistics.pstdev(vals)
        quads: list[list[float]] = [[], [], [], []]
        for idx, (_, r) in enumerate(res):
            y, x = divmod(idx, w - 2)
            quads[(0 if y < (h - 2) / 2 else 2)
                  + (0 if x < (w - 2) / 2 else 1)].append(r)
        qsds = [statistics.pstdev(q) for q in quads]
        sds.append(sd)
        spreads.append((max(qsds) - min(qsds)) / sd if sd > 1e-9 else 0.0)
    if not sds:
        return ForensicSignal(
            name="sensor_noise", status="unavailable",
            detail="Sampled frames could not be decoded for sensor-noise "
                   "analysis.")
    sd_mean = sum(sds) / len(sds)
    spread_mean = sum(spreads) / len(spreads)
    n = len(sds)
    if sd_mean < _NOISE_FLAT_SD:
        return ForensicSignal(
            name="sensor_noise", status="signal", value=sd_mean,
            detail=(f"Mean sensor-noise residual {sd_mean:.2f} below "
                    f"{_NOISE_FLAT_SD:.1f} across {n} sampled frame(s): "
                    "flat lighting with no measurable sensor pattern. "
                    "Consistent with synthetic or heavily smoothed media, "
                    "but smooth camera content (sky, walls) fires this too. "
                    "Weak proxy only."))
    if spread_mean < _NOISE_UNIFORM_SPREAD:
        return ForensicSignal(
            name="sensor_noise", status="signal", value=spread_mean,
            detail=(f"Noise spread {spread_mean:.2f} below "
                    f"{_NOISE_UNIFORM_SPREAD:.1f} across {n} sampled "
                    "frame(s): noise is unnaturally uniform across each "
                    "frame instead of varying like camera sensor noise. "
                    "Consistent with synthetic uniform noise. Weak proxy "
                    "only."))
    return ForensicSignal(
        name="sensor_noise", status="no_signal", value=spread_mean,
        detail=(f"Sensor-noise residual {sd_mean:.2f} varies across "
                f"regions (spread {spread_mean:.2f}) over {n} sampled "
                "frame(s); noise structure resembles camera capture more "
                "than flat synthetic output. Denoising or compression can "
                "mimic either side. Weak proxy only."))


def _light_signal(frames: list[Path]) -> ForensicSignal:
    import statistics

    if not frames:
        return ForensicSignal(
            name="light_bias", status="unavailable",
            detail="No sampled frames available for light-bias analysis.")
    try:
        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="light_bias", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    ratios: list[float] = []
    for frame in frames[:_PIXEL_FRAMES]:
        try:
            with Image.open(frame) as im:
                gray = im.convert("L").resize((64, 64))
                w, h = gray.size
                res = _residuals(_flat_pixels(gray), w, h)
        except Exception:
            continue
        sh = [r for v, r in res if v < 85]
        hi = [r for v, r in res if v > 170]
        if len(sh) < 0.05 * len(res) or len(hi) < 0.05 * len(res):
            continue
        sh_sd, hi_sd = statistics.pstdev(sh), statistics.pstdev(hi)
        if max(sh_sd, hi_sd) <= 1e-9:
            continue
        ratios.append(min(sh_sd, hi_sd) / max(sh_sd, hi_sd))
    if not ratios:
        return ForensicSignal(
            name="light_bias", status="unavailable",
            detail="Too few shadow and highlight pixels across sampled "
                   "frames to compare noise by luminance.")
    ratio = sum(ratios) / len(ratios)
    n = len(ratios)
    if ratio >= _LIGHT_UNIFORM_RATIO:
        return ForensicSignal(
            name="light_bias", status="signal", value=ratio,
            detail=(f"Shadow/highlight noise ratio {ratio:.2f} at or above "
                    f"{_LIGHT_UNIFORM_RATIO:.2f} across {n} sampled "
                    "frame(s): shadows and highlights carry near-identical "
                    "noise, i.e. flat uniform lighting with no natural "
                    "light bias. Consistent with synthetic lighting. Weak "
                    "proxy only."))
    return ForensicSignal(
        name="light_bias", status="no_signal", value=ratio,
        detail=(f"Shadow/highlight noise ratio {ratio:.2f} across {n} "
                "sampled frame(s): noise differs between shadows and "
                "highlights (natural light bias). Weak proxy only."))


def _reencode_signal(frames: list[Path]) -> ForensicSignal:
    if not frames:
        return ForensicSignal(
            name="reencode_layer", status="unavailable",
            detail="No sampled frames available for re-encode analysis.")
    try:
        from PIL import Image
    except ImportError:
        return ForensicSignal(
            name="reencode_layer", status="unavailable",
            detail="Pillow (media extra) is not installed.")
    ratios: list[float] = []
    for frame in frames[:_PIXEL_FRAMES]:
        try:
            with Image.open(frame) as im:
                gray = im.convert("L")
                w, h = gray.size
                if w < 16 or h < 16:
                    continue
                px = _flat_pixels(gray)
        except Exception:
            continue
        bsum, bn, isum, inn = 0.0, 0, 0.0, 0
        for y in range(h):
            row = y * w
            for x in range(w - 1):
                d = abs(px[row + x + 1] - px[row + x])
                if (x + 1) % 8 == 0:
                    bsum += d
                    bn += 1
                else:
                    isum += d
                    inn += 1
        for y in range(h - 1):
            for x in range(w):
                d = abs(px[(y + 1) * w + x] - px[y * w + x])
                if (y + 1) % 8 == 0:
                    bsum += d
                    bn += 1
                else:
                    isum += d
                    inn += 1
        interior = isum / inn if inn else 0.0
        if interior < 0.05:
            continue  # too flat to measure block structure
        ratios.append((bsum / bn) / interior if bn else 1.0)
    if not ratios:
        return ForensicSignal(
            name="reencode_layer", status="unavailable",
            detail="Sampled frames too flat or too small to measure "
                   "block-boundary structure.")
    ratio = sum(ratios) / len(ratios)
    n = len(ratios)
    if ratio >= _BLOCK_SIGNAL_RATIO:
        return ForensicSignal(
            name="reencode_layer", status="signal", value=ratio,
            detail=(f"Block-boundary gradient ratio {ratio:.2f} at or above "
                    f"{_BLOCK_SIGNAL_RATIO:.1f} across {n} sampled frame(s): "
                    "consistent with at least one re-encode generation "
                    "(platform compression or screen recording). Step 1 of "
                    "3: a re-encode layer is present, so sensor-noise "
                    "fingerprints from these pixels are unreliable and the "
                    "pixel-level signals are discounted. This finding alone "
                    "cannot tell whether the source was synthetic."))
    return ForensicSignal(
        name="reencode_layer", status="no_signal", value=ratio,
        detail=(f"Block-boundary gradient ratio {ratio:.2f} within normal "
                f"range across {n} sampled frame(s); no re-encode layer "
                "measured. Heavy noise can mask block structure, so "
                "absence here does not prove original capture."))


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
