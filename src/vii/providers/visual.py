"""Visual perception providers (SAM-class detection/segmentation/tracking).

STATUS — local provider IMPLEMENTED, SAM 3.1 adapter IMPLEMENTED:

- ``LocalVisualPerceptionProvider`` (``VII_VISUAL_PERCEPTION_PROVIDER=local``)
  is a real, working provider: it samples frames with FFmpeg under a
  documented policy and produces frame-level observations (shot segments,
  inter-frame change, frame timing) from those frames with Pillow. Sparse
  sampled frames are never described as continuous tracking, and it
  produces no masks and no prompt-based object detections.
- ``SamVisualPerceptionProvider`` (``VII_VISUAL_PERCEPTION_PROVIDER=sam``)
  implements the SAM 3.1 contract verified against Meta's official
  documentation: model ``sam-3.1``, ``POST /v1/responses`` on the Meta
  Model API base URL, the same Bearer key as the rest of the API,
  concept prompts (one noun phrase per request), native-video or
  Files-API input, and the documented per-frame ``<Nf>id<|box|><|mask|>``
  output grammar with stable per-object tracking ids. Capability state
  stays ``configured_unverified`` (a per-configuration state, not a
  history flag). LIVE VERIFIED 2026-11-03: a direct provider call
  (concept "flower", public MDN flower MP4, video_url input) returned
  125 segmentation observations (response model ``sam-3.1``, wire
  format matching the documented grammar), and a full pipeline run
  returned 363 segmentation observations with the job succeeded and
  mask payloads stored under ``visual_masks/`` — see
  ``docs/ARCHITECTURE.md``. Video is billed per frame (50-frame
  minimum per request), so routine tests use a fake transport only.
- ``UnavailableVisualPerceptionProvider`` — explains the precise reason
  and never returns empty success.
- ``get_visual_perception_provider`` — deterministic selection from
  settings.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from vii.domain.schemas import VisualObservation
from vii.errors import UnsupportedCapabilityError

if TYPE_CHECKING:
    from vii.config import Settings


class VisualPerceptionUnavailableError(UnsupportedCapabilityError):
    """Visual perception was requested but no verified adapter is usable."""


class VisualPerceptionProvider(Protocol):
    """Normalized visual perception interface (provider-independent)."""

    name: str
    model: str

    def capabilities(self) -> dict:
        """Return {supported_inputs, supports_tracking, status, notes}."""
        ...

    def perceive_video(self, media_ref: str, *, asset_id: str = "",
                       prompts: list[str] | None = None,
                       sampling_mode: str = "native_video") -> list[VisualObservation]:
        """Return observations for a video reference, or raise a typed error."""
        ...


class UnavailableVisualPerceptionProvider:
    """Honest blocked state: explains why, never fabricates observations."""

    name = "unavailable"
    model = ""

    def __init__(self, reason: str):
        self.reason = reason

    def capabilities(self) -> dict:
        return {"supported_inputs": [], "supports_tracking": False,
                "status": "blocked", "notes": self.reason}

    def perceive_video(self, media_ref: str, *, asset_id: str = "",
                       prompts: list[str] | None = None,
                       sampling_mode: str = "native_video") -> list[VisualObservation]:
        raise VisualPerceptionUnavailableError(self.reason)


class LocalVisualPerceptionProvider:
    """Working local provider: FFmpeg frame sampling + Pillow analysis.

    Sampling policy (recorded on every observation): frames are sampled
    at ``fps`` frames/second, at most ``max_frames`` frames, via
    ``vii.media.ffmpeg.sample_frames``. Observations describe sampled
    frames only — shot segments and inter-frame change — never
    continuous object tracking, segmentation masks, or prompt-based
    detection (those require a contract-verified SAM adapter).
    """

    name = "local"
    model = "pillow-frame-analysis-1"

    def __init__(self, ffmpeg_bin: str = "ffmpeg", fps: float = 0.2,
                 max_frames: int = 12):
        self.ffmpeg_bin = ffmpeg_bin
        self.fps = fps
        self.max_frames = max_frames

    def capabilities(self) -> dict:
        import shutil
        missing = []
        try:
            import PIL  # noqa: F401
        except ImportError:
            missing.append("Pillow (media extra)")
        if not shutil.which(self.ffmpeg_bin):
            missing.append(f"ffmpeg binary {self.ffmpeg_bin!r}")
        if missing:
            return {"supported_inputs": [], "supports_tracking": False,
                    "status": "blocked",
                    "notes": ("local visual perception unavailable: missing "
                              + ", ".join(missing))}
        return {"supported_inputs": ["local_file"],
                "supports_tracking": False,
                "status": "available_local",
                "notes": (f"Frame analysis on FFmpeg-sampled frames "
                          f"(fps={self.fps}, max {self.max_frames} frames): "
                          "shot segments and inter-frame change only. "
                          "Sparse frames are not continuous tracking; no "
                          "masks or prompt-based detections are produced.")}

    def perceive_video(self, media_ref: str, *, asset_id: str = "",
                       prompts: list[str] | None = None,
                       sampling_mode: str = "sampled_frames") -> list[VisualObservation]:
        from pathlib import Path

        if prompts:
            raise VisualPerceptionUnavailableError(
                "local visual perception cannot honour text prompts; "
                "prompt-based detection/segmentation requires the SAM "
                "3.1 provider (VII_VISUAL_PERCEPTION_PROVIDER=sam)")
        if str(media_ref).startswith(("http://", "https://")):
            raise VisualPerceptionUnavailableError(
                "local visual perception requires a local media file, "
                "not a remote URL; no frames were sampled")
        src = Path(str(media_ref))
        if not src.is_file():
            raise VisualPerceptionUnavailableError(
                f"local visual perception: media file not found: {src}")
        caps = self.capabilities()
        if caps["status"] != "available_local":
            raise VisualPerceptionUnavailableError(caps["notes"])

        import shutil
        import tempfile

        from vii.media import ffmpeg as ffmpeg_mod

        workdir = Path(tempfile.mkdtemp(prefix="vii_visual_"))
        try:
            try:
                frames = ffmpeg_mod.sample_frames(
                    src, workdir, fps=self.fps, max_frames=self.max_frames,
                    ffmpeg_bin=self.ffmpeg_bin)
            except Exception as e:
                raise VisualPerceptionUnavailableError(
                    f"frame sampling failed: {e}") from e
            if not frames:
                raise VisualPerceptionUnavailableError(
                    "frame sampling produced no frames; no observations")
            return self._observe(frames, asset_id)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _observe(self, frames, asset_id: str) -> list[VisualObservation]:
        from PIL import Image

        def signature(path) -> bytes | None:
            try:
                with Image.open(path) as im:
                    return im.convert("L").resize((16, 16)).tobytes()
            except Exception:
                return None

        def distance(a: bytes, b: bytes) -> float:
            return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / (255.0 * len(a))

        observations: list[VisualObservation] = []
        shot = 0
        prev: bytes | None = None
        for i, frame in enumerate(frames):
            sig = signature(frame)
            if sig is None:
                continue
            changed = prev is not None and distance(prev, sig) > 0.18
            if i == 0 or changed:
                shot += 1
                observations.append(VisualObservation(
                    observation_id=f"obs_{i:03d}_shot",
                    asset_id=asset_id, provider=self.name, model=self.model,
                    timestamp_ms=int(i / self.fps * 1000) if self.fps else None,
                    frame_index=i, observation_type="shot_segment",
                    object_id=f"shot-{shot:03d}", label="shot start",
                    description=(
                        f"Shot {shot} starts at sampled frame {i} "
                        f"(sampling: fps={self.fps}, max {self.max_frames} "
                        "frames; sparse frames, not continuous tracking)."),
                    sampling_mode="sampled_frames"))
            elif prev is not None:
                d = distance(prev, sig)
                if d > 0.05:
                    observations.append(VisualObservation(
                        observation_id=f"obs_{i:03d}_motion",
                        asset_id=asset_id, provider=self.name,
                        model=self.model,
                        timestamp_ms=int(i / self.fps * 1000) if self.fps else None,
                        frame_index=i, observation_type="inter_frame_change",
                        object_id=f"shot-{shot:03d}",
                        label="inter-frame change",
                        description=(
                            f"Mean pixel change vs previous sampled frame: "
                            f"{d:.3f} (sampled frames only)."),
                        sampling_mode="sampled_frames"))
            prev = sig
        if not observations:
            raise VisualPerceptionUnavailableError(
                "sampled frames could not be read; no observations produced")
        return observations


# -- SAM 3.1 wire-grammar parser -------------------------------------------
# Documented output (Meta SAM 3.1 docs, "Read segmentation output"):
# one line per frame in the output_text lane:
#   <Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;x=0;y=0[;c=..];data=H,W,ENC PAYLOAD|>,...
# ENC is "~" (lossless, default) or "!" (one_bit); PAYLOAD is base85 and
# may itself contain commas or "~"/"!" characters, so a mask token ends
# only at a "|>" followed by the next record (",<id><|box;") or end of
# line. Mask payloads are stored verbatim as encoded artifacts — VII
# does not decode them (raster decoding is the official parser's job).

_SAM_BOX_RE = re.compile(
    r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)"
    r"(?:;c=([0-9.]+))?\|>")
_SAM_MASK_HEAD_RE = re.compile(
    r"<\|mask;x=0;y=0(?:;c=([0-9.]+))?;data=(\d+),(\d+),([~!])")
_SAM_MASK_END_RE = re.compile(r"\|>(?=,\d+<\||$)")
_SAM_FRAME_RE = re.compile(r"<(\d+)f>")
_SAM_ID_RE = re.compile(r"(\d+)")


def parse_sam_output(text: str, *, asset_id: str = "", model: str = "sam-3.1",
                     prompt: str = "", mask_dir: str | Path | None = None,
                     request_id: str = "") -> list[VisualObservation]:
    """Parse SAM 3.1 output_text into VisualObservations (pure, no I/O
    except optional mask-payload artifact files under ``mask_dir``).

    Empty text is the documented zero-match outcome and returns [].
    Malformed lines are skipped, never guessed at.
    """
    observations: list[VisualObservation] = []
    if not text or not text.strip():
        return observations
    out_dir = Path(mask_dir) if mask_dir else None
    safe_asset = re.sub(r"[^A-Za-z0-9_.-]+", "_", asset_id or "asset")
    for line in text.splitlines():
        line = line.strip()
        fm = _SAM_FRAME_RE.match(line)
        if fm is None:
            continue
        frame = int(fm.group(1))
        pos = fm.end()
        while pos < len(line):
            im = _SAM_ID_RE.match(line, pos)
            if im is None:
                break
            oid = im.group(1)
            bm = _SAM_BOX_RE.match(line, im.end())
            if bm is None:
                break
            mm = _SAM_MASK_HEAD_RE.match(line, bm.end())
            if mm is None:
                break
            em = _SAM_MASK_END_RE.search(line, mm.end())
            if em is None:
                break
            payload = line[mm.end():em.start()]
            x1, y1, x2, y2, w, h = (int(bm.group(i)) for i in range(1, 7))
            confidence = bm.group(7) or mm.group(1)
            mh, mw = int(mm.group(2)), int(mm.group(3))
            encoding = "lossless" if mm.group(4) == "~" else "one_bit"
            mask_ref = None
            if out_dir is not None:
                out_dir.mkdir(parents=True, exist_ok=True)
                mask_path = out_dir / f"{safe_asset}_f{frame:04d}_obj{oid}.mask"
                mask_path.write_text(payload)
                mask_ref = str(mask_path)
            geometry: dict = {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                              "w": w, "h": h,
                              "mask": {"height": mh, "width": mw,
                                       "encoding": encoding,
                                       "stored": mask_ref is not None}}
            if confidence:
                geometry["confidence"] = float(confidence)
            observations.append(VisualObservation(
                observation_id=f"obs_f{frame:04d}_obj{oid}",
                asset_id=asset_id, provider="sam", model=model,
                timestamp_ms=None,  # frame index is known; fps is not
                frame_index=frame, observation_type="segmentation",
                object_id=oid, label=prompt,
                description=(
                    f"SAM 3.1 segmentation of {prompt!r} on frame {frame} "
                    f"(object id {oid} is a stable track id within this "
                    "response; mask payload stored as an encoded artifact, "
                    "not decoded by VII)."),
                geometry=geometry, mask_ref=mask_ref,
                request_id=request_id, sampling_mode="native_video"))
            pos = em.end()
            if pos < len(line) and line[pos] == ",":
                pos += 1
    return observations


class SamVisualPerceptionProvider:
    """SAM 3.1 hosted adapter (docs-verified contract, live unverified).

    One concept prompt per request (documented: multi-concept syntax
    returns zero matches), at most ``max_concepts`` requests per video.
    Remote media is passed as ``video_url``/``image_url``; local video
    is uploaded once via the Files API (``purpose=user_data``) and
    referenced by ``file_id``; local images go as base64 data URLs.
    Zero matches is a valid documented outcome and returns [] for that
    concept. Provider/transport failures are wrapped in the typed
    unavailable error so an optional pipeline stage reports blocked
    instead of failing the whole analysis. Video is billed per frame
    (50-frame minimum per request) — callers decide when to spend.
    """

    name = "sam"

    def __init__(self, client=None, model: str = "sam-3.1",
                 mask_dir: str | Path | None = None, max_concepts: int = 3):
        self._client = client
        self.model = model or "sam-3.1"
        self.mask_dir = Path(mask_dir) if mask_dir else None
        self.max_concepts = max(1, max_concepts)

    def capabilities(self) -> dict:
        if self._client is None or not self._client.live:
            return {"supported_inputs": [], "supports_tracking": False,
                    "status": "blocked",
                    "notes": ("SAM 3.1 selected but no API key is "
                              "configured (VII_SAM_API_KEY or "
                              "MODEL_API_KEY); no observations produced.")}
        return {"supported_inputs": ["public_url", "local_file"],
                "supports_tracking": True,
                "status": "configured_unverified",
                "notes": (f"SAM 3.1 adapter (model {self.model}) "
                          "implemented against the docs-verified "
                          "Responses API contract; live acceptance "
                          "verified 2026-11-03 (direct + pipeline "
                          "calls returned segmentation observations; "
                          "see docs/ARCHITECTURE.md). Status stays "
                          "configured_unverified per configuration. "
                          "Concept prompts only (one noun phrase per "
                          "request); video billed per frame, 50-frame "
                          "minimum.")}

    def perceive_video(self, media_ref: str, *, asset_id: str = "",
                       prompts: list[str] | None = None,
                       sampling_mode: str = "native_video") -> list[VisualObservation]:
        if self._client is None or not self._client.live:
            raise VisualPerceptionUnavailableError(
                "SAM 3.1 visual perception selected but no API key is "
                "configured (VII_SAM_API_KEY or MODEL_API_KEY); no "
                "observations produced")
        concepts: list[str] = []
        seen: set[str] = set()
        for p in prompts or []:
            c = str(p).strip()
            if c and c.lower() not in seen and len(c) <= 80:
                seen.add(c.lower())
                concepts.append(c)
        concepts = concepts[:self.max_concepts]
        if not concepts:
            raise VisualPerceptionUnavailableError(
                "SAM 3.1 requires at least one concept prompt (a short "
                "noun phrase such as 'red bicycle'); none were supplied, "
                "so no request was sent and no observations produced")
        media_part = self._media_part(media_ref)
        observations: list[VisualObservation] = []
        for concept in concepts:
            payload = {
                "model": self.model,
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": concept}, media_part]}],
                "stream": False,
                "metadata": {"mask_encoding": "one_bit",
                             "include_confidence": "true"},
            }
            try:
                resp = self._client.responses_create(payload)
            except Exception as e:
                raise VisualPerceptionUnavailableError(
                    f"SAM 3.1 request failed for concept {concept!r}: "
                    f"{str(e)[:300]}") from e
            from vii.meta import response_parser as rp
            text = rp.output_text(resp if isinstance(resp, dict) else {})
            observations.extend(parse_sam_output(
                text, asset_id=asset_id, model=self.model, prompt=concept,
                mask_dir=self.mask_dir,
                request_id=str(resp.get("id", "")) if isinstance(resp, dict) else ""))
        return observations

    def _media_part(self, media_ref: str) -> dict:
        s = str(media_ref)
        image_exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        if s.startswith(("http://", "https://")):
            if s.lower().split("?")[0].endswith(image_exts):
                return {"type": "input_image", "image_url": s}
            return {"type": "input_video", "video_url": s}
        src = Path(s)
        if not src.is_file():
            raise VisualPerceptionUnavailableError(
                f"SAM 3.1 visual perception: media file not found: {src}")
        suffix = src.suffix.lower()
        if suffix in image_exts:
            import base64
            mime = "image/png" if suffix == ".png" else "image/jpeg"
            data = base64.b64encode(src.read_bytes()).decode()
            return {"type": "input_image",
                    "image_url": f"data:{mime};base64,{data}"}
        if suffix in (".mp4", ".mov"):
            try:
                up = self._client.upload_video(str(src))
            except Exception as e:
                raise VisualPerceptionUnavailableError(
                    f"SAM 3.1 media upload failed: {str(e)[:300]}") from e
            return {"type": "input_video", "file_id": up["file_id"]}
        raise VisualPerceptionUnavailableError(
            f"SAM 3.1 accepts MP4/MOV video (H.264/H.265/MPEG-4) or "
            f"image files; {suffix or 'extensionless'} input is not "
            "supported and was not sent")


_BLOCKED_REASON = (
    "no visual perception provider is usable for this configuration; "
    "select VII_VISUAL_PERCEPTION_PROVIDER=local (working frame "
    "analysis) or sam (SAM 3.1 adapter, docs-verified contract, needs "
    "an API key). No observations were produced.")


def get_visual_perception_provider(settings: Settings):
    """Select the visual perception provider for these settings.

    Deterministic and honest: ``local`` returns the working frame-
    analysis provider, ``sam`` returns the SAM 3.1 adapter when a key
    is configured (``configured_unverified`` until a live call proves
    acceptance), and anything else returns the unavailable provider
    with the most specific reason the configuration supports.
    """
    if not settings.enable_visual_perception:
        return UnavailableVisualPerceptionProvider(
            "visual perception is disabled "
            "(VII_ENABLE_VISUAL_PERCEPTION=false); no observations produced")
    if not settings.visual_perception_provider:
        return UnavailableVisualPerceptionProvider(
            "visual perception is enabled but no provider is selected "
            "(VII_VISUAL_PERCEPTION_PROVIDER is empty); " + _BLOCKED_REASON)
    if settings.visual_perception_provider.strip().lower() == "local":
        return LocalVisualPerceptionProvider(settings.ffmpeg_bin)
    if settings.visual_perception_provider.strip().lower() == "sam":
        # Docs-verified contract: SAM 3.1 uses the same Bearer key as the
        # rest of the Meta Model API; VII_SAM_API_KEY may override it.
        key = (settings.sam_api_key or settings.effective_api_key or "").strip()
        if not key:
            return UnavailableVisualPerceptionProvider(
                "SAM 3.1 visual perception selected but no API key is "
                "configured (VII_SAM_API_KEY or MODEL_API_KEY); no "
                "observations produced")
        from vii.meta.client import MetaClient
        model = settings.sam_model.strip() or "sam-3.1"
        client = MetaClient(key, settings.meta_base_url, model,
                            timeout_s=settings.request_timeout_s,
                            max_retries=settings.max_retries)
        return SamVisualPerceptionProvider(
            client=client, model=model,
            mask_dir=Path(settings.storage_dir) / "visual_masks")
    return UnavailableVisualPerceptionProvider(
        f"unknown visual perception provider "
        f"{settings.visual_perception_provider!r}; " + _BLOCKED_REASON)
