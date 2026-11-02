"""SHA-256 exact hashing + perceptual hashing of sampled frames."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def phash_frames(frames: list[Path]) -> list[str]:
    """Perceptual hashes; returns [] if imagehash/Pillow unavailable."""
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        return []
    out = []
    for fp in frames:
        try:
            with Image.open(fp) as im:
                out.append(str(imagehash.phash(im)))
        except Exception:
            continue
    return out


def phash_distance(a: str, b: str) -> int | None:
    try:
        import imagehash
        return int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))
    except Exception:
        return None
