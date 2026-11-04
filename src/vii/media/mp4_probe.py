"""Lightweight ISO-BMFF (MP4/MOV) metadata parsing, pure Python, no FFmpeg.

Only what ingestion needs: the ``ftyp`` major brand and the ``moov/mvhd``
duration. Anything unparsable yields ``None`` fields, never a guess; callers
may optionally enrich with ffprobe when it happens to be installed.
"""
from __future__ import annotations

import struct
from pathlib import Path


def _read_boxes(f, end: int):
    """Yield (box_type, content_offset, content_size) for boxes up to ``end``."""
    while f.tell() + 8 <= end:
        header = f.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:  # 64-bit largesize
            raw = f.read(8)
            if len(raw) < 8:
                return
            size = struct.unpack(">Q", raw)[0]
            header_size = 16
        elif size == 0:  # box extends to end of file/container
            size = end - (f.tell() - header_size)
        if size < header_size:
            return
        content_offset = f.tell()
        content_size = size - header_size
        yield box_type.decode("latin-1"), content_offset, content_size
        # Callers may move the file pointer while inspecting a box (e.g. to
        # read the ftyp brand); always resume at the next sibling box.
        f.seek(content_offset + content_size)


def probe_mp4(path: str | Path) -> dict:
    """Return {container, major_brand, duration_s} for an MP4/MOV file.

    ``duration_s`` is None when no readable mvhd box exists. Raises nothing:
    malformed input returns {"container": "unknown", ...}.
    """
    out: dict = {"container": "unknown", "major_brand": "", "duration_s": None}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            file_end = f.tell()
            f.seek(0)
            for box_type, offset, size in _read_boxes(f, file_end):
                if box_type == "ftyp":
                    f.seek(offset)
                    brand = f.read(4).decode("latin-1", "replace").strip().lower()
                    out["major_brand"] = brand
                    out["container"] = "mov" if brand in ("qt  ", "qt") else "mp4"
                elif box_type == "moov":
                    moov_end = offset + size
                    for child_type, child_off, _ in _read_boxes(f, moov_end):
                        if child_type != "mvhd":
                            continue
                        f.seek(child_off)
                        header = f.read(4)
                        if len(header) < 4:
                            return out  # truncated mvhd: duration stays unknown
                        version = header[0]
                        if version == 1:
                            raw = f.read(8 + 8 + 4 + 8)  # ctime, mtime, timescale, duration
                            if len(raw) < 28:
                                return out
                            timescale, duration = struct.unpack(">IQ", raw[16:28])
                        else:
                            raw = f.read(4 + 4 + 4 + 4)
                            if len(raw) < 16:
                                return out
                            timescale, duration = struct.unpack(">II", raw[8:16])
                        if timescale:
                            out["duration_s"] = duration / timescale
                        return out
                    return out
    except (OSError, struct.error):
        return out
    return out
