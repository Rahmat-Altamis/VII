"""Authorized Facebook Page API media retrieval.

Requires a Page token (VII_FACEBOOK_PAGE_TOKEN). Verifies the actual API
response before assuming the media binary exists; arbitrary public
permalink downloads are NOT promised. Failures instruct local upload.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from vii.media import social as social_mod

log = logging.getLogger("vii.platforms.facebook")

GRAPH_BASE = "https://graph.facebook.com/v21.0"


def extract_post_id(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if urlparse(url).hostname in ("fb.watch", "www.fb.watch", "fb.com", "www.fb.com"):
        return path.strip("/")
    parts = [p for p in path.split("/") if p]
    for i, p in enumerate(parts):
        if p in ("posts", "videos", "reel", "watch") and i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else ""


def fetch_media(url: str, token: str, timeout_s: float = 30.0) -> dict:
    """Resolve a Facebook URL to an official media binary URL when allowed."""
    if not token:
        return {"ok": False, "platform": "facebook",
                "error": "VII_FACEBOOK_PAGE_TOKEN not configured; provide a local MP4 upload.",
                "auth_method": "none", "status": 0, "media_binary_acquired": False}
    info = social_mod.classify_url(url)
    post_id = extract_post_id(url)
    if not post_id:
        return {"ok": False, "platform": "facebook", "kind": info["kind"],
                "error": "No post/video id could be extracted from this URL; "
                         "provide a local MP4 upload.",
                "auth_method": "facebook_page_api",
                "status": 0, "media_binary_acquired": False}
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(f"{GRAPH_BASE}/{post_id}",
                           params={"fields": "source,permalink_url,created_time",
                                   "access_token": token})
            if r.status_code != 200:
                return {"ok": False, "platform": "facebook", "kind": info["kind"],
                        "post_id": post_id,
                        "error": f"Page API lookup failed (HTTP {r.status_code}); "
                                 "provide a local MP4 upload.",
                        "auth_method": "facebook_page_api",
                        "status": r.status_code, "media_binary_acquired": False}
            data = r.json()
            media_url = data.get("source", "")
            if not media_url:
                return {"ok": False, "platform": "facebook", "kind": info["kind"],
                        "post_id": post_id,
                        "error": "Page API returned no downloadable media binary for this "
                                 "post (permissions/copyright); provide a local MP4 upload.",
                        "auth_method": "facebook_page_api",
                        "status": r.status_code, "media_binary_acquired": False}
            return {"ok": True, "platform": "facebook", "kind": info["kind"],
                    "post_id": post_id, "media_url": media_url,
                    "permalink": data.get("permalink_url", url),
                    "created_time": data.get("created_time", ""),
                    "auth_method": "facebook_page_api",
                    "status": r.status_code, "media_binary_acquired": True}
    except Exception as e:  # network/timeout, surface, never silent
        log.warning("facebook fetch failed: %s", str(e)[:200])
        return {"ok": False, "platform": "facebook", "kind": info["kind"],
                "post_id": post_id,
                "error": f"Facebook Page API request failed: {str(e)[:200]}; "
                         "provide a local MP4 upload.",
                "auth_method": "facebook_page_api",
                "status": 0, "media_binary_acquired": False}
