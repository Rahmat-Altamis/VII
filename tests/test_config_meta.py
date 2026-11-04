"""Areas 1-2: configuration + Meta provider setup."""
from vii.config import Settings
from vii.meta.client import MetaClient
from vii.meta.search import build_search_payload, web_search_tool


def test_offline_without_key(tmp_path):
    Settings(_env_file=None, VII_OFFLINE_MODE=False, VII_STORAGE_DIR=tmp_path)
    s2 = Settings(_env_file=None, MODEL_API_KEY="", META_BASE_URL="https://api.meta.ai/v1",
                  VII_STORAGE_DIR=tmp_path)
    assert not s2.live_mode


def test_live_mode_needs_key_and_online(tmp_path):
    s = Settings(_env_file=None, MODEL_API_KEY="k", VII_OFFLINE_MODE=False, VII_STORAGE_DIR=tmp_path)
    assert s.live_mode
    s3 = Settings(_env_file=None, MODEL_API_KEY="k", VII_OFFLINE_MODE=True, VII_STORAGE_DIR=tmp_path)
    assert not s3.live_mode


def test_redacted_hides_key(tmp_path):
    s = Settings(_env_file=None, MODEL_API_KEY="secret", VII_STORAGE_DIR=tmp_path)
    assert "secret" not in str(s.redacted())


def test_meta_client_init():
    c = MetaClient("k", "https://api.meta.ai/v1", "muse-spark-1.3")
    assert c.live and c.model == "muse-spark-1.3"


def test_search_tool_shape():
    assert web_search_tool() == {"type": "web_search"}
    p = build_search_payload("q", "muse-spark-1.3")
    assert p["tools"] == [{"type": "web_search"}]
    assert "web_search_call.results" in p["include"]
