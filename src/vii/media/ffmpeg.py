"""Safe FFmpeg/ffprobe invocation (no shell=True, bounded args, timeouts)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
    except FileNotFoundError as e:
        raise FFmpegError(f"binary not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"timed out: {' '.join(cmd[:3])}") from e


def probe(path: str | Path, ffprobe_bin: str = "ffprobe") -> dict:
    p = _run([ffprobe_bin, "-v", "quiet", "-print_format", "json",
              "-show_format", "-show_streams", str(path)])
    if p.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {p.stderr[:500]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise FFmpegError("ffprobe returned invalid JSON") from e


def _parse_fps(value: str) -> float:
    """Parse an ffprobe avg_frame_rate string ('30000/1001', '25', …)."""
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


def tool_versions(ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> dict:
    """Presence + version line for each binary (port of legacy media.check_ffmpeg)."""
    import shutil

    info: dict[str, str | bool] = {}
    for tool, binary in (("ffmpeg", ffmpeg_bin), ("ffprobe", ffprobe_bin)):
        found = shutil.which(binary)
        info[tool] = bool(found)
        if found:
            try:
                out = _run([binary, "-version"], timeout=10)
                info[f"{tool}_version"] = (out.stdout.splitlines() or [""])[0][:120]
            except Exception as exc:  # noqa: BLE001
                info[f"{tool}_version"] = f"error: {exc}"
    return info


def metadata_summary(probed: dict) -> dict:
    fmt = probed.get("format", {})
    streams = probed.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "format": fmt.get("format_name", ""),
        "duration_s": duration,
        "size_bytes": int(fmt.get("size", 0) or 0),
        "video_codec": video.get("codec_name", ""),
        "width": video.get("width"), "height": video.get("height"),
        "fps": _parse_fps(str(video.get("avg_frame_rate", "0") or "0")),
        "audio_codec": audio.get("codec_name", ""),
        "has_audio": bool(audio),
        "container_ext_ok": True,
    }


def extract_audio_wav(src: str | Path, dst: str | Path, ffmpeg_bin: str = "ffmpeg",
                      sample_rate: int = 24000,
                      start_s: float = 0.0, end_s: float | None = None) -> Path:
    """Extract a transcription-ready WAV: mono, 16-bit PCM, 24 kHz default.

    Window [start_s, end_s) preserves timeline alignment; the caller adds
    start_s as the segment offset. Matches the documented conversion:
    mono PCM WAV at 16 or 24 kHz.
    """
    dst = Path(dst)
    cmd = [ffmpeg_bin, "-y", "-v", "error", "-ss", str(max(0.0, start_s))]
    if end_s is not None:
        cmd += ["-to", str(end_s)]
    cmd += ["-i", str(src), "-ac", "1", "-ar", str(sample_rate),
            "-c:a", "pcm_s16le", "-map_metadata", "-1", str(dst)]
    p = _run(cmd)
    if p.returncode != 0 or not dst.exists():
        raise FFmpegError(f"audio extraction failed: {p.stderr[:500]}")
    return dst


def extract_audio(src: str | Path, dst: str | Path, ffmpeg_bin: str = "ffmpeg",
                  sample_rate: int = 16000) -> Path:
    dst = Path(dst)
    p = _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(src),
              "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)])
    if p.returncode != 0 or not dst.exists():
        raise FFmpegError(f"audio extraction failed: {p.stderr[:500]}")
    return dst


def convert_to_mp4(src: str | Path, dst: str | Path, ffmpeg_bin: str = "ffmpeg") -> Path:
    dst = Path(dst)
    p = _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(src),
              "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", str(dst)], timeout=600)
    if p.returncode != 0 or not dst.exists():
        raise FFmpegError(f"mp4 conversion failed: {p.stderr[:500]}")
    return dst


def thumbnail(src: str | Path, dst: str | Path, at_s: float = 1.0,
              ffmpeg_bin: str = "ffmpeg") -> Path:
    dst = Path(dst)
    p = _run([ffmpeg_bin, "-y", "-v", "error", "-ss", str(at_s), "-i", str(src),
              "-frames:v", "1", str(dst)])
    if p.returncode != 0 or not dst.exists():
        raise FFmpegError(f"thumbnail failed: {p.stderr[:300]}")
    return dst


def sample_frames(src: str | Path, out_dir: str | Path, fps: float = 0.2,
                  max_frames: int = 12, ffmpeg_bin: str = "ffmpeg") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = _run([ffmpeg_bin, "-y", "-v", "error", "-i", str(src),
              "-vf", f"fps={fps}", "-frames:v", str(max_frames),
              str(out / "frame_%03d.jpg")])
    if p.returncode != 0:
        raise FFmpegError(f"frame sampling failed: {p.stderr[:300]}")
    return sorted(out.glob("frame_*.jpg"))
