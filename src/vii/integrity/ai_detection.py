"""AI-generation detection over sampled frames (hosted VLM judgments).

Each sampled frame is sent to the configured provider model with a
structured verdict prompt. The video-level result is a probability,
the mean AI-confidence across judged frames, with the per-frame
distribution preserved. This is probabilistic evidence with measured
error rates (0.80 accuracy on a 40-image AI-art/real-art sample), never
a real/fake verdict. Remote URLs are not fetched; they are unavailable.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vii.meta.client import MetaClient

PROMPT = """You are a synthetic-media analyst. Decide whether this image is
AI-generated or a real photo/painting. Look for generation tells
(anatomy errors, garbled text, inconsistent lighting, plastic skin,
impossible geometry) versus camera/paint evidence (sensor noise,
natural imperfections, artist brushwork). Return ONLY a JSON object:
{"verdict": "ai_generated"|"real", "confidence": 0.0-1.0,
"reasons": ["short reason", ...]}"""


def judge_frame(image_bytes: bytes, client: MetaClient, model: str) -> dict:
    """One hosted judgment for a single frame image."""
    from vii.meta.response_parser import output_text

    data = base64.b64encode(image_bytes).decode()
    payload = {"model": model,
               "input": [{"role": "user", "content": [
                   {"type": "input_text", "text": PROMPT},
                   {"type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{data}"}]}]}
    resp = client.responses_create(payload)
    text = output_text(resp if isinstance(resp, dict) else {})
    start, end = text.find("{"), text.rfind("}")
    parsed = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
    if parsed.get("verdict") not in ("ai_generated", "real"):
        raise ValueError("detector returned no usable verdict")
    try:
        conf = float(parsed.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = min(1.0, max(0.0, conf))
    reasons = parsed.get("reasons", []) or []
    return {"verdict": parsed["verdict"], "confidence": conf,
            "ai_probability": conf if parsed["verdict"] == "ai_generated"
            else 1.0 - conf,
            "reasons": [str(r) for r in reasons][:5]}


def assess_frames(frames: list[Path], client: MetaClient | None,
                  model: str, max_frames: int = 5) -> dict[str, Any]:
    """Judge up to max_frames sampled frames; aggregate honestly.

    Returns {status, ai_probability, frames_judged, frames, note}.
    ``frames`` keeps every per-frame verdict. Failures of individual
    frames are recorded, not silently dropped.
    """
    if client is None or not client.live:
        return {"status": "unavailable", "ai_probability": None,
                "frames_judged": 0, "frames": [],
                "note": "no live provider client; no judgment made"}
    judged: list[dict] = []
    for fp in frames[:max(1, max_frames)]:
        try:
            result = judge_frame(Path(fp).read_bytes(), client, model)
            judged.append({"frame": Path(fp).name, "ok": True, **result})
        except Exception as e:
            judged.append({"frame": Path(fp).name, "ok": False,
                           "error": f"{type(e).__name__}: {str(e)[:200]}"})
    good = [j for j in judged if j["ok"]]
    if not good:
        return {"status": "failed", "ai_probability": None,
                "frames_judged": 0, "frames": judged,
                "note": "no frame produced a usable judgment"}
    probs = [g["ai_probability"] for g in good]
    status = "success" if len(good) == len(judged) else "partial"
    return {"status": status,
            "ai_probability": round(sum(probs) / len(probs), 3),
            "frames_judged": len(good), "frames": judged,
            "note": ("Mean AI-probability across judged frames; "
                     "calibration measured at 0.80 accuracy on a 40-image "
                     "AI-art/real-art sample, art domain, not video frames.")}
