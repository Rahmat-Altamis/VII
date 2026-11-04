"""Phase 2 (handoff): single retry layer, keystore, log redaction.
Fake transports only, no live provider calls, no real keys."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from vii.errors import ProviderError, ProviderPermissionError
from vii.meta.client import MetaClient


class _HttpError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = SimpleNamespace(status_code=status)


class _FakeSDK:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0
        outer = self

        class _Responses:
            def create(self, **payload):
                outer.calls += 1
                raise outer.errors.pop(0)

        self.responses = _Responses()


def _client_with_sdk(errors):
    c = MetaClient("test-key", "https://api.example/v1", "m",
                   timeout_s=1.0, max_retries=2)
    sdk = _FakeSDK(errors)
    c._client = sdk
    return c, sdk


@pytest.mark.parametrize("status", [400, 401, 403, 413])
def test_responses_never_retries_client_errors(status, monkeypatch):
    import vii.meta.client as cm
    monkeypatch.setattr(cm.time, "sleep", lambda _s: None)
    c, sdk = _client_with_sdk([_HttpError(status)] * 5)
    with pytest.raises(ProviderError):
        c.responses_create({"model": "m", "input": []})
    assert sdk.calls == 1


def test_sdk_retries_are_disabled():
    c = MetaClient("test-key", "https://api.example/v1", "m", max_retries=2)
    captured = {}

    class _OpenAI:
        def __init__(self, **kw):
            captured.update(kw)

    import sys
    import types
    fake = types.ModuleType("openai")
    fake.OpenAI = _OpenAI
    monkey = sys.modules.get("openai")
    sys.modules["openai"] = fake
    try:
        c._sdk()
    finally:
        if monkey is not None:
            sys.modules["openai"] = monkey
    assert captured.get("max_retries") == 0


def test_transcribe_auth_failure_short_circuits(monkeypatch, tmp_path):
    import vii.meta.client as cm
    monkeypatch.setattr(cm.time, "sleep", lambda _s: None)
    c = MetaClient("test-key", "https://api.example/v1", "m",
                   timeout_s=1.0, max_retries=2)
    calls = {"n": 0}

    def _post(*a, **k):
        calls["n"] += 1
        return SimpleNamespace(status_code=401, text="unauthorized",
                               json=lambda: {})

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    with pytest.raises(ProviderPermissionError) as ei:
        c.transcribe(str(audio), _post=_post)
    assert calls["n"] == 1
    assert isinstance(ei.value, ProviderPermissionError)


def test_upload_never_retries_400(monkeypatch, tmp_path):
    import vii.meta.client as cm
    monkeypatch.setattr(cm.time, "sleep", lambda _s: None)
    c = MetaClient("test-key", "https://api.example/v1", "m",
                   timeout_s=1.0, max_retries=2)
    calls = {"n": 0}

    class _Files:
        @staticmethod
        def create(file=None, purpose=None):
            calls["n"] += 1
            raise _HttpError(400)

    c._client = SimpleNamespace(files=_Files)
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    with pytest.raises(ProviderError):
        c.upload_video(str(media))
    assert calls["n"] == 1


def test_upload_same_content_is_not_reuploaded(tmp_path):
    c = MetaClient("test-key", "https://api.example/v1", "m",
                   timeout_s=1.0, max_retries=0)
    calls = {"n": 0}

    class _Files:
        @staticmethod
        def create(file=None, purpose=None):
            calls["n"] += 1
            return SimpleNamespace(id="file_1")

    c._client = SimpleNamespace(files=_Files)
    media = tmp_path / "v.mp4"
    media.write_bytes(b"same-bytes")
    assert c.upload_video(str(media)) == {"file_id": "file_1"}
    assert c.upload_video(str(media)) == {"file_id": "file_1"}
    assert calls["n"] == 1


# -- keystore ---------------------------------------------------------------

def test_keystore_load_falls_back_when_keyring_empty(tmp_path, monkeypatch):
    import vii.keystore as ks
    ks.store_api_key.__wrapped__ if hasattr(ks.store_api_key, "__wrapped__") else None
    # Write fallback file directly, then simulate empty keyring.
    fp = ks._fallback_file(tmp_path)
    fp.write_text('{"meta_api_key": "fallback-key"}')
    fake = SimpleNamespace(
        get_password=lambda *a: None,
        set_password=lambda *a: None,
        delete_password=lambda *a: None)
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    assert ks.load_api_key(tmp_path) == "fallback-key"


def test_keystore_clear_removes_fallback(tmp_path, monkeypatch):
    import vii.keystore as ks
    fake = SimpleNamespace(
        get_password=lambda *a: None,
        set_password=lambda *a: (_ for _ in ()).throw(RuntimeError("no backend")),
        delete_password=lambda *a: None)
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    ks.store_api_key("some-key", tmp_path)
    assert ks.load_api_key(tmp_path) == "some-key"
    ks.store_api_key("", tmp_path)
    assert ks.load_api_key(tmp_path) == ""


# -- log redaction ------------------------------------------------------------

def test_redact_masks_bearer_tokens():
    from vii.logging_setup import redact
    assert "secret-token-123" not in redact("Authorization: Bearer secret-token-123")
    assert "secret-token-123" not in redact("Bearer secret-token-123")
    assert "sk-live-abcdef" not in redact("api_key=sk-live-abcdef")


def test_handler_level_redaction_covers_child_loggers(capsys):
    from vii.logging_setup import setup_logging
    setup_logging()
    logging.getLogger("vii.meta").warning("sending Bearer secret-token-999 now")
    err = capsys.readouterr().err
    assert "secret-token-999" not in err
