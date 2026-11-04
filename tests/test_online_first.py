"""Online-first behavior: real provider by default, demo only on explicit opt-in."""
import json

import pytest

from vii.config import Settings
from vii.domain.schemas import AnalysisCreate
from vii.errors import ProviderConfigurationError, ProviderError


def _live_settings(tmp_path):
    return Settings(_env_file=None, MODEL_API_KEY="test-key-not-real",
                    VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                    VII_STORAGE_DIR=tmp_path)


def _url_req(**kw):
    return AnalysisCreate(
        source={"kind": "public_url", "url": "https://example.com/v.mp4"}, **kw)


def test_default_config_selects_online_provider(tmp_path):
    s = Settings(_env_file=None, VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                 VII_STORAGE_DIR=tmp_path)
    assert s.demo_enabled is False
    assert _url_req().demo_requested is False


def test_missing_credentials_fail_clearly_on_create(tmp_path):
    from vii.application.services import AnalysisService
    svc = AnalysisService(Settings(_env_file=None,
        VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db", VII_STORAGE_DIR=tmp_path))
    with pytest.raises(ProviderConfigurationError, match="MODEL_API_KEY"):
        svc.create(_url_req())


def test_provider_error_fails_job_never_demo(tmp_path):
    from vii.application.services import AnalysisService
    svc = AnalysisService(_live_settings(tmp_path))

    class Boom:
        live = True

        def responses_create(self, payload):
            raise ProviderError("simulated provider failure")

    svc.pipeline.client = Boom()
    jid = svc.create(_url_req())
    with pytest.raises(ProviderError):
        svc.run(jid)
    detail = svc.get(jid)
    assert detail["status"] == "failed"
    assert detail["claims"] == []


def test_explicit_demo_is_labeled_and_synthetic(settings):
    from vii.application.services import AnalysisService
    svc = AnalysisService(settings)
    assert settings.demo_enabled is True
    jid = svc.create(_url_req(demo=True))
    payload = svc.run(jid)
    assert payload["offline"] is True
    assert any("SYNTHETIC DEMO" in lim for lim in payload["limitations"])


def test_local_hashing_works_without_credentials(tmp_path):
    from vii.media.hashing import sha256_file
    p = tmp_path / "clip.bin"
    p.write_bytes(b"synthetic-bytes")
    assert len(sha256_file(p)) == 64


class _FakeClient:
    """Mocked provider transport: no network, no credits."""

    live = True

    def upload_video(self, path, purpose="user_data"):
        return {"file_id": "file_test123"}

    def responses_create(self, payload):
        if "tools" in payload:  # web search request
            return {"id": "resp_search", "output": [
                {"type": "web_search_call", "id": "ws_1", "results": [
                    {"url": "https://www.britannica.com/place/Eiffel-Tower",
                     "title": "Eiffel Tower", "snippet": "330 metres tall"}]},
                {"type": "message", "content": [
                    {"type": "output_text", "text": "The tower is 330 metres.",
                     "annotations": [{"type": "url_citation",
                                      "url": "https://www.britannica.com/place/Eiffel-Tower",
                                      "title": "Eiffel Tower", "start_index": 0,
                                      "end_index": 10}]}]}]}
        understanding = {"summary": "A tower.", "factual_claims": [
            {"text": "The Eiffel Tower is 330 metres tall.", "start_s": 1.0, "end_s": 3.0}]}
        return {"id": "resp_vu", "output": [
            {"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(understanding)}]}]}


def test_mocked_provider_success_maps_to_typed_result(tmp_path):
    from vii.application.services import AnalysisService
    svc = AnalysisService(_live_settings(tmp_path))
    svc.pipeline.client = _FakeClient()
    jid = svc.create(_url_req())
    payload = svc.run(jid)
    assert payload["offline"] is False
    assert svc.get(jid)["status"] == "succeeded"
    assert payload["claims"][0]["text"] == "The Eiffel Tower is 330 metres tall."
    assert payload["sources"], "search evidence must come from the provider response"
    assert payload["claims"][0]["status"] != "not_yet_analyzed"
