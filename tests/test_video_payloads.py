"""Areas 3-5: URL payload, file_id payload, unsupported formats."""
import pytest

from vii.domain.schemas import AnalysisCreate
from vii.media import ingestion
from vii.meta.video import build_file_id_payload, build_url_payload


def test_url_payload_uses_input_video():
    p = build_url_payload("https://cdn.example.com/v.mp4", "muse-spark-1.3")
    blocks = p["input"][0]["content"]
    assert any(b.get("type") == "input_video" and b["video_url"].endswith("v.mp4") for b in blocks)


def test_file_id_payload():
    p = build_file_id_payload("file_123", "muse-spark-1.3")
    blocks = p["input"][0]["content"]
    assert any(b.get("type") == "input_file" and b["file_id"] == "file_123" for b in blocks)


def test_unsupported_format_rejected(tmp_path):
    f = tmp_path / "x.xyz"
    f.write_bytes(b"0" * 100)
    with pytest.raises(ValueError, match="unsupported format"):
        ingestion.validate_source(
            AnalysisCreate(source={"kind": "local_file", "local_path": str(f)}).source, 512, tmp_path)


def test_ssrf_guard_blocks_private():
    with pytest.raises(ValueError, match="SSRF|public"):
        ingestion.validate_source(
            AnalysisCreate(source={"kind": "public_url", "url": "http://169.254.169.254/x"}).source,
            512, __import__("pathlib").Path("/tmp"))
