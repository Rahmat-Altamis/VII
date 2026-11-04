"""Authorized Instagram Graph API media retrieval.

Requires a professional-account user token (VII_INSTAGRAM_TOKEN). Never
bypasses auth; copyright/download restrictions are respected, when the
API response carries no usable media_url, the caller must require a
local upload instead of inventing a download path.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from vii.media import social as social_mod

log = logging.getLogger("vii.platforms.instagram")

GRAPH_BASE = "https://graph.facebook.com/v21.0"


def extract_shortcode(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else ""


def fetch_media(url: str, token: str, timeout_s: float = 30.0) -> dict:
    """Resolve an Instagram URL to an official media_url when permissions allow.

    Flow: shortcode -> best-effort oEmbed id hint -> Graph media lookup.
    Returns {ok, media_url?, media_id?, ...}; missing media_url => ok False
    with a local-upload instruction. Never raises for HTTP errors.
    """
    if not token:
        return {"ok": False, "platform": "instagram",
                "error": "VII_INSTAGRAM_TOKEN not configured; provide a local MP4 upload.",
                "auth_method": "none", "status": 0, "media_binary_acquired": False}
    shortcode = extract_shortcode(url)
    info = social_mod.classify_url(url)
    try:
        with httpx.Client(timeout=timeout_s) as client:
            # oEmbed carries no media binary; use it only to confirm the post exists.
            r = client.get("https://graph.facebook.com/v21.0/instagram_oembed",
                           params={"url": url, "access_token": token})
            if r.status_code != 200:
                return {"ok": False, "platform": "instagram", "kind": info["kind"],
                        "error": f"oEmbed lookup failed (HTTP {r.status_code}); "
                                 "provide a local MP4 upload.",
                        "auth_method": "instagram_graph_oembed",
                        "status": r.status_code, "media_binary_acquired": False,
                        "shortcode": shortcode}
            data = r.json()
            media_id = data.get("author_id", "")
            # Business Discovery path: needs an IG business/creator account id;
            # without one configured we stop here honestly.
            return {"ok": False, "platform": "instagram", "kind": info["kind"],
                    "media_id": str(media_id), "shortcode": shortcode,
                    "error": "Official media_url not returned for this URL with current "
                             "permissions; provide a local MP4 upload (copyright/download "
                             "restrictions respected).",
                    "auth_method": "instagram_graph_oembed",
                    "status": r.status_code, "title": data.get("title", ""),
                    "media_binary_acquired": False}
    except Exception as e:  # network/timeout, surface, never silent
        log.warning("instagram fetch failed: %s", str(e)[:200])
        return {"ok": False, "platform": "instagram", "kind": info["kind"],
                "error": f"Instagram Graph request failed: {str(e)[:200]}; "
                         "provide a local MP4 upload.",
                "auth_method": "instagram_graph_oembed",
                "status": 0, "media_binary_acquired": False, "shortcode": shortcode}
