"""Input validation, SSRF guards, metadata. No unofficial downloaders.

Acquisition priority (product decision):
1. Authorized Instagram Graph API where permissions/media allow.
2. Authorized Facebook Page API where permissions/media allow.
3. Direct public media URLs via Muse Spark native video input.
4. User-provided local upload via Meta Files API.

Platform page URLs (reel/post/watch/share) are recognized by vii.media.social
for metadata, but NEVER fetched with unofficial downloaders. When authorized
access cannot return the video binary, the caller must require a local file.
"""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import vii.media.ffmpeg as ffmpeg_mod
from vii.domain.enums import SourceKind
from vii.domain.schemas import MediaIngestionResult, VideoSourceIn
from vii.errors import (
    InvalidUploadError,
    MediaDurationExceededError,
    UnsupportedMediaError,
    UploadTooLargeError,
)

SUPPORTED_EXTS = {".mp4"}
CONVERTIBLE_EXTS = {".mkv", ".mov", ".webm", ".avi", ".m4v"}
MAX_URL_LEN = 2048


def validate_source(src: VideoSourceIn, max_mb: int, storage: Path) -> dict:
    if src.kind == SourceKind.LOCAL_FILE:
        if not src.local_path:
            raise ValueError("local_path is required for file input")
        p = Path(src.local_path)
        if not p.is_file():
            raise ValueError(f"file not found: {src.local_path}")
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > max_mb:
            raise ValueError(f"file too large: {size_mb:.1f}MB > {max_mb}MB")
        ext = p.suffix.lower()
        needs_convert = ext not in SUPPORTED_EXTS
        if needs_convert and ext not in CONVERTIBLE_EXTS:
            raise ValueError(f"unsupported format {ext}; supported: mp4 (convertible: {sorted(CONVERTIBLE_EXTS)})")
        return {"path": str(p), "ext": ext, "needs_convert": needs_convert,
                "size_mb": round(size_mb, 2)}
    # URL input
    if not src.url or len(src.url) > MAX_URL_LEN:
        raise ValueError("a valid public URL is required")
    host = (urlparse(src.url).hostname or "")
    _ssrf_check(host, src.url)
    return {"url": src.url, "host": host}


def _ssrf_check(host: str, url: str) -> None:
    """Block non-global targets for any server-side fetch (fail-closed).

    ``is_global`` is the single test: it rejects private, loopback,
    link-local, multicast, reserved, CGNAT and documentation ranges.
    A DNS failure or an empty answer rejects the URL here instead of
    deferring to fetch time.
    """
    if not host:
        raise ValueError("URL has no host")
    if host.lower() in ("localhost",):
        raise ValueError("SSRF guard: localhost URLs are not allowed")
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC)
    except (socket.gaierror, UnicodeError) as e:
        raise ValueError(f"SSRF guard: cannot resolve host {host!r}") from e
    if not infos:
        raise ValueError(f"SSRF guard: cannot resolve host {host!r}")
    for _fam, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global or str(ip) in ("169.254.169.254",):
            raise ValueError(f"SSRF guard: {host} resolves to non-public IP")


def ensure_mp4(src_path: str | Path, storage: Path, ffmpeg_bin: str,
               original_sha: str) -> tuple[Path, bool, str]:
    """Return (usable_path, was_converted, usable_sha). Original file is preserved."""
    src = Path(src_path)
    if src.suffix.lower() == ".mp4":
        from vii.media.hashing import sha256_file
        return src, False, original_sha or sha256_file(src)
    dst = storage / "media" / f"{src.stem}_converted.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    from vii.media.hashing import sha256_file
    ffmpeg_mod.convert_to_mp4(src, dst, ffmpeg_bin)
    return dst, True, sha256_file(dst)


# -- Ingestion-only inspection (no job, no worker, no provider) ------------
#
# This path deliberately imports no provider, pipeline, worker, or
# persistence module: validating media must be testable without credentials
# and must never spend provider credits. FFmpeg/ffprobe are optional
# enrichment only, a supported native MP4 is fully validated without them.

_EXT_CONTAINER = {
    ".mp4": "mp4", ".m4v": "mp4", ".mov": "mov",
    ".mkv": "mkv", ".webm": "webm", ".avi": "avi",
}
# Signature families: an .mkv and a .webm share the EBML header, and an
# .m4v is an MP4 brand, family match is what the signature can prove.
_CONTAINER_FAMILY = {
    "mp4": "mp4", "mov": "mp4", "mkv": "ebml", "webm": "ebml", "avi": "avi",
}


def sniff_container(path: str | Path) -> str:
    """Identify a container from magic bytes (not the file name).

    Returns mp4 | mov | mkv | webm | avi | unknown. Never raises.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return "unknown"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        brand = head[8:12].decode("latin-1", "replace").strip().lower()
        return "mov" if brand in ("qt",) else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML: Matroska vs WebM by DocType
        return "webm" if b"webm" in head else "mkv"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    return "unknown"


def inspect_local_media(path: str | Path, max_mb: int = 512,
                        max_seconds: int = 3600,
                        ffprobe_bin: str | None = None) -> MediaIngestionResult:
    """Validate + hash a local media file without any analysis side effects.

    Raises InvalidUploadError / UploadTooLargeError /
    UnsupportedMediaError / MediaDurationExceededError (all ValueErrors)
    with explicit messages. Duration comes from the pure-Python MP4 parser
    first; ffprobe is used only when a binary name is supplied, the tool is
    installed, and the MP4 parser could not determine a duration.
    """
    import os
    import shutil

    from vii.media.hashing import sha256_file
    from vii.media.mp4_probe import probe_mp4

    p = Path(path)
    if not p.is_file():
        raise InvalidUploadError(f"file not found: {path}")
    if not os.access(p, os.R_OK):
        raise InvalidUploadError(f"file is not readable: {path}")
    size_bytes = p.stat().st_size
    if size_bytes == 0:
        raise InvalidUploadError(f"file is empty: {path}")
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > max_mb:
        raise UploadTooLargeError(f"file too large: {size_mb:.1f}MB > {max_mb}MB")
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS and ext not in CONVERTIBLE_EXTS:
        raise UnsupportedMediaError(
            f"unsupported format {ext or '(none)'}; supported: mp4 "
            f"(convertible: {sorted(CONVERTIBLE_EXTS)})")

    container = sniff_container(p)
    expected = _EXT_CONTAINER.get(ext, "unknown")
    signature_ok = (
        container != "unknown"
        and _CONTAINER_FAMILY.get(container) == _CONTAINER_FAMILY.get(expected))
    if not signature_ok:
        raise UnsupportedMediaError(
            f"media signature mismatch: extension {ext} implies {expected}, "
            f"but file signature is {container}")

    limitations: list[str] = []
    duration_s: float | None = None
    duration_source = "unknown"
    has_audio: bool | None = None
    if container in ("mp4", "mov"):
        probed = probe_mp4(p)
        if probed.get("duration_s"):
            duration_s = float(probed["duration_s"])
            duration_source = "mp4_mvhd"
    if duration_s is None and ffprobe_bin and shutil.which(ffprobe_bin):
        try:
            meta = ffmpeg_mod.metadata_summary(ffmpeg_mod.probe(p, ffprobe_bin))
            if meta.get("duration_s"):
                duration_s = float(meta["duration_s"])
                duration_source = "ffprobe"
            has_audio = bool(meta.get("has_audio"))
        except Exception:  # probing is optional enrichment, never a blocker
            limitations.append("ffprobe enrichment failed; duration unknown")
    if duration_s is None:
        limitations.append(
            "duration could not be determined locally; it was not guessed "
            "and no provider was contacted")
    elif duration_s > max_seconds:
        raise MediaDurationExceededError(
            f"video too long: {duration_s:.0f}s > {max_seconds}s")

    return MediaIngestionResult(
        storage_ref=str(p), sha256=sha256_file(p), size_bytes=size_bytes,
        size_mb=round(size_mb, 2), extension=ext, container=container,
        signature_ok=True, duration_s=duration_s,
        duration_source=duration_source, has_audio=has_audio,
        native_video_ready=(ext == ".mp4" and container == "mp4"),
        needs_conversion=ext in CONVERTIBLE_EXTS, limitations=limitations)
