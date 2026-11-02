"""Source ranking helpers — prefer official/primary/credible material."""
from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL_SUFFIXES = (".gov", ".edu", ".int", ".europa.eu")
PRIMARY_HINTS = ("official", "press release", "dataset", "transcript", "court", "filing")


def publisher_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def credibility_tier(url: str, title: str = "") -> int:
    """3 official/primary, 2 established press, 1 other, 0 unknown."""
    host = publisher_of(url).lower()
    blob = f"{host} {title}".lower()
    if host.endswith(OFFICIAL_SUFFIXES) or any(h in blob for h in PRIMARY_HINTS):
        return 3
    if any(n in host for n in ("reuters.", "apnews.", "bbc.", "npr.", "pbs.", "nature.",
                               "science.", "nytimes.", "washingtonpost.", "theguardian.")):
        return 2
    return 1 if host else 0


def rank(urls: list[str]) -> list[str]:
    return sorted(urls, key=lambda u: credibility_tier(u), reverse=True)
