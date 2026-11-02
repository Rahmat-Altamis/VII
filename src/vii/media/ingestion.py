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
from vii.domain.enums import AcquisitionMethod, SourceKind
from vii.domain.schemas import VideoSourceIn

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
    """Block private/loopback/link-local targets for any server-side fetch."""
    if not host:
        raise ValueError("URL has no host")
    if host.lower() in ("localhost",):
        raise ValueError("SSRF guard: localhost URLs are not allowed")
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC)
    except socket.gaierror:
        return  # DNS failure surfaces later at fetch time, not here
    for fam, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
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
