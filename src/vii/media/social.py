"""Instagram / Facebook URL recognition and supported acquisition paths.

Honesty rules (product decision — no unofficial downloaders):
- A post/watch-page URL is NOT a directly consumable media URL. Only direct
  media hosts (fbcdn / scontent / instagram cdn .mp4) can be offered to Meta
  native input; page URLs go through authorized platform APIs (Instagram Graph
  / Facebook Page) or the caller must require a local upload.
- Never bypass authentication, paywalls, private access, DRM. Failures return
  {'ok': False} and are surfaced, never silent.
"""
from __future__ import annotations

from urllib.parse import urlparse

INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "instagr.am"}
FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com",
                  "fb.com", "fb.watch"}
DIRECT_MEDIA_HINTS = ("fbcdn.net", "scontent.", ".mp4")


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname.lower() if urlparse(url).hostname else ""
    except Exception:
        return ""


def classify_url(url: str) -> dict:
    """Return {platform, kind, native_ok, host} for a social or generic URL.

    platform: instagram | facebook | generic | invalid
    kind: reel | post | watch | video | story | profile | media_file | unknown
    native_ok: True only for direct media files (cdn .mp4 etc.)
    """
    url = normalize_url(url)
    if not url:
        return {"platform": "invalid", "kind": "unknown", "native_ok": False, "host": ""}
    host = host_of(url)
    path = urlparse(url).path or "/"

    def _kind(candidates: list[tuple[str, str]]) -> str:
        for prefix, name in candidates:
            if path.startswith(prefix):
                return name
        return "unknown"

    if host in INSTAGRAM_HOSTS or host.endswith(".instagram.com"):
        kind = _kind([("/reel/", "reel"), ("/reels/", "reel"), ("/p/", "post"),
                      ("/tv/", "video"), ("/stories/", "story")])
        if not url.lower().endswith(".mp4"):
            return {"platform": "instagram", "kind": kind, "native_ok": False, "host": host}
        return {"platform": "instagram", "kind": "media_file",
                "native_ok": True, "host": host}
    if host in FACEBOOK_HOSTS or host.endswith(".facebook.com"):
        kind = _kind([("/reel/", "reel"), ("/watch", "watch"), ("/video", "video"),
                      ("/stories/", "story"), ("/posts/", "post"), ("/share/", "share")])
        if path in ("/", "") and host == "fb.watch":
            kind = "share"  # short link, needs resolution
        return {"platform": "facebook", "kind": kind, "native_ok": False, "host": host}
    native_ok = url.lower().endswith(".mp4") or any(h in host for h in DIRECT_MEDIA_HINTS)
    return {"platform": "generic",
            "kind": "media_file" if native_ok else "unknown",
            "native_ok": native_ok, "host": host}


def resolution_plan(url: str) -> dict:
    """Decide the ingestion path and record exactly what will be attempted.

    Returns {platform, kind, strategy, note} where strategy is one of:
    'native_url' (direct media file) | 'platform_api_or_upload'
    (post/watch URL -> authorized Instagram Graph / Facebook Page API, else
    require a local upload) | 'invalid'.
    """
    info = classify_url(url)
    if info["platform"] == "invalid":
        return {**info, "strategy": "invalid",
                "note": "Not a usable URL. Provide a public post/watch link with platform "
                        "API credentials configured, a direct media URL, or a local MP4."}
    if info["native_ok"]:
        return {**info, "strategy": "native_url",
                "note": "Direct media URL: offered to Meta native video input unchanged."}
    return {**info, "strategy": "platform_api_or_upload",
            "note": (f"{info['platform']} {info['kind']} page: a page URL is not a media file. "
                     "Attempt authorized platform API retrieval (recorded as platform_api); "
                     "when the API cannot return the video binary, require a local upload. "
                     "No auth/paywall/DRM bypass.")}
