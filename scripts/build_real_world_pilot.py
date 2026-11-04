"""Build the real-world pilot evaluation dataset (full frame coverage).

For each evaluation video: probe metadata, SHA-256, then enumerate EVERY
decoded video frame in [0, 300s) via ffprobe frame output streamed line
by line (no fps filter, no sampling, no dedup, PTS preserved, VFR-safe),
and count decoded audio frames in the same window. Frame images are not
persisted; frame_index.jsonl is the frame ledger. Provider AI analysis
is tracked separately and is NOT run by this builder.

Usage: .venv/bin/python scripts/build_real_world_pilot.py
Originals in ~/Downloads are never moved, renamed, or modified.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vii.media.hashing import sha256_file  # noqa: E402

DOWNLOADS = Path.home() / "Downloads"
OUT = (Path(__file__).resolve().parent.parent
       / "data" / "evaluation" / "real_world_pilot")
WINDOW_S = 300.0

# The evaluation collection (user-listed). Actual on-disk spelling of the
# "ai character" file contains "genereted"; matched by prefix below.
TARGETS = [
    "AI advertisement.mp4",
    "ai character and ai genereted tech video.mp4",
    "ai generated propaganda.mp4",
    "Ai simple mass produced fake info video.mp4",
    "claude ai made.mp4",
    "claude tech ai made.mp4",
    "cutoff movie and dubbed.mp4",
    "mass reposted hoax video.mp4",
    "reddit story spam.mp4",
    "reframe and reposted video.mp4",
    "repost.mp4",
    "reposted video.mp4",
    "simple massproduced.mp4",
    "simple massproduceds.mp4",
]


def probe_json(path: Path, entries: str, *extra: str) -> dict:
    cmd = ["ffprobe", "-v", "error", *extra, "-show_entries", entries,
           "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return json.loads(out.stdout or "{}")


def stream_frames(path: Path, stream: str, index_path: Path) -> dict:
    """Enumerate every decoded frame in [0, WINDOW_S), streamed.

    Returns counts. Video frames are appended to index_path as JSONL with
    sequential index, PTS and presentation time (never derived from FPS).
    """
    cmd = ["ffprobe", "-v", "error", "-select_streams", stream,
           "-show_entries", "frame=pts,pts_time,key_frame,pict_type",
           "-of", "csv=p=0", str(path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    count = in_window = 0
    first_pts = last_pts = None
    fout = open(index_path, "w") if index_path else None
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            parts = [p.strip() for p in line.strip().split(",")]
            if len(parts) < 2:
                continue
            # ffprobe CSV order is key_frame,pts,pts_time,pict_type;
            # identify pts_time as the decimal field, tolerantly.
            pts_time = None
            pts = parts[1] if len(parts) > 2 else ""
            for part in parts:
                if "." in part:
                    try:
                        pts_time = float(part)
                    except ValueError:
                        pass
            if pts_time is None:
                continue
            count += 1
            if pts_time < WINDOW_S:
                in_window += 1
                first_pts = pts_time if first_pts is None else first_pts
                last_pts = pts_time
                if fout:
                    fout.write(json.dumps({
                        "frame_index": in_window - 1,
                        "pts": pts, "pts_time_s": pts_time,
                        "key_frame": parts[0] if parts[0] in ("0", "1") else "",
                        "pict_type": parts[-1] if parts[-1].isalpha() else "",
                    }) + "\n")
    finally:
        if fout:
            fout.close()
        proc.wait(timeout=120)
    return {"decoded_frames": count, "frames_in_window": in_window,
            "first_pts_time_s": first_pts, "last_pts_time_s": last_pts}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "annotations").mkdir(exist_ok=True)
    (OUT / "frames").mkdir(exist_ok=True)
    (OUT / "runs").mkdir(exist_ok=True)

    all_mp4 = sorted(p.name for p in DOWNLOADS.glob("*.mp4"))
    excluded = [n for n in all_mp4 if n not in TARGETS]
    videos = []
    coverage = []
    for i, name in enumerate(sorted(TARGETS), start=1):
        vid = f"vid_{i:03d}"
        path = DOWNLOADS / name
        meta = probe_json(path, "stream:format")
        streams = meta.get("streams", [])
        vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
        astreams = [s for s in streams if s.get("codec_type") == "audio"]
        frame_dir = OUT / "frames" / vid
        frame_dir.mkdir(parents=True, exist_ok=True)
        vframes = stream_frames(path, "v:0", frame_dir / "frame_index.jsonl")
        aframes = (stream_frames(path, "a:0", None) if astreams
                   else {"decoded_frames": 0, "frames_in_window": 0})
        record = {
            "video_id": vid,
            "original_filename": name,
            "original_path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "container": (meta.get("format") or {}).get("format_name", ""),
            "video_codec": vstream.get("codec_name", ""),
            "width": vstream.get("width"),
            "height": vstream.get("height"),
            "avg_frame_rate": vstream.get("avg_frame_rate", ""),
            "nominal_frame_rate": vstream.get("r_frame_rate", ""),
            "duration_s": float((meta.get("format") or {}).get("duration", 0) or 0),
            "probe_frame_count": vstream.get("nb_frames", ""),
            "decoded_frame_count": vframes["decoded_frames"],
            "audio_streams": [{
                "codec": a.get("codec_name", ""),
                "channels": a.get("channels"),
                "sample_rate": a.get("sample_rate", ""),
            } for a in astreams],
            "audio_decoded_frames_in_window": aframes["frames_in_window"],
            "window_s": WINDOW_S,
            "frames_in_window": vframes["frames_in_window"],
            "first_pts_time_s": vframes["first_pts_time_s"],
            "last_pts_time_s": vframes["last_pts_time_s"],
        }
        videos.append(record)
        coverage.append({
            "video_id": vid,
            "frames_decoded": vframes["frames_in_window"],
            "frames_submitted_to_provider": 0,
            "frames_analyzed_by_provider": 0,
            "frames_failed": 0,
            "audio_frames_decoded": aframes["frames_in_window"],
            "status": "blocked",
            "note": ("All frames decoded and indexed locally. Provider "
                     "full-frame analysis was not run: the provider "
                     "native-video path samples internally and exposes no "
                     "per-frame analysis ledger, so full-frame AI analysis "
                     "cannot be claimed."),
        })
        (OUT / "annotations" / f"{vid}.json").write_text(json.dumps({
            "video_id": vid, "original_filename": name,
            "filename_hint_not_label": name.rsplit(".", 1)[0],
            "ground_truth": None, "labels": [],
            "annotation_status": "pending",
            "notes": "Filename is a hint only, never a ground-truth label.",
        }, indent=2))
        print(f"{vid} {name}: decoded={vframes['frames_in_window']} "
              f"audio={aframes['frames_in_window']}", flush=True)

    (OUT / "videos.jsonl").write_text(
        "".join(json.dumps(v) + "\n" for v in videos))
    (OUT / "dataset_manifest.json").write_text(json.dumps({
        "dataset": "real_world_pilot", "version": "0.1",
        "source_directory": str(DOWNLOADS),
        "window": "[0, 300s), every decoded frame, no sampling/dedup",
        "video_count": len(videos),
        "inventory_total_mp4": len(all_mp4),
        "excluded_not_evaluation_collection": excluded,
        "videos": [{"video_id": v["video_id"],
                    "original_filename": v["original_filename"],
                    "sha256": v["sha256"]} for v in videos],
    }, indent=2))
    (OUT / "runs" / "coverage.json").write_text(json.dumps(coverage, indent=2))
    (OUT / "dataset.csv").write_text(
        "video_id,source_url,platform,storage_ref,sha256,duration_s,title\n"
        + "".join(
            f"{v['video_id']},,generic,{v['original_path']},{v['sha256']},"
            f"{v['duration_s']},{v['original_filename']}\n" for v in videos))
    print(f"done: {len(videos)} videos, excluded={len(excluded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
