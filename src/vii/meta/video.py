"""Native video-understanding payloads: input_video/video_url + file_id modes."""
from __future__ import annotations

VIDEO_ANALYSIS_INSTRUCTIONS = """Analyze this video natively (visual + audio together) and return JSON:
{"summary": str, "events": [str], "visual_observations": [str],
 "on_screen_text": [str], "entities": {"people": [], "organizations": [], "objects": [], "locations": []},
 "factual_claims": [{"text": str, "start_s": number|null, "end_s": number|null}],
 "ambiguous_statements": [str], "open_questions": [str]}
Keep claims atomic (one fact each). Distinguish factual claims from opinions."""


def build_url_payload(video_url: str, model: str, instructions: str | None = None) -> dict:
    """Mode A, reference a publicly accessible video via input_video + video_url."""
    return {
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": instructions or VIDEO_ANALYSIS_INSTRUCTIONS},
                {"type": "input_video", "video_url": video_url},
            ],
        }],
    }


def build_file_id_payload(file_id: str, model: str, instructions: str | None = None) -> dict:
    """Mode B, reference an uploaded file via its file_id."""
    return {
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": instructions or VIDEO_ANALYSIS_INSTRUCTIONS},
                {"type": "input_file", "file_id": file_id},
            ],
        }],
    }
