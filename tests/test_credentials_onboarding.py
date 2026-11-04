"""Credential onboarding: precedence, terminal setup, safe test, readiness.

No live requests: the connection test runs against a fake transport, and
keyring access is faked. No real keys anywhere.
"""
from __future__ import annotations


def _settings(tmp_path, **kw):
    from vii.config import Settings
    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("VII_STORAGE_DIR", tmp_path)
    kw.setdefault("VII_DATABASE_URL", f"sqlite:///{tmp_path}/vii.db")
    return Settings(_env_file=None, **kw)


# -- precedence (verified behavior) ------------------------------------------

def test_env_key_takes_precedence_over_keyring(tmp_path, monkeypatch):
    import vii.keystore as ks
    monkeypatch.setattr(ks, "load_api_key", lambda d: "keyring-key")
    s = _settings(tmp_path, MODEL_API_KEY="env-key")
    assert s.effective_api_key == "env-key"
    assert s.key_source == "env"


def test_keyring_used_when_env_empty(tmp_path, monkeypatch):
    import vii.keystore as ks
    monkeypatch.setattr(ks, "load_api_key", lambda d: "keyring-key")
    s = _settings(tmp_path, MODEL_API_KEY="")
    assert s.effective_api_key == "keyring-key"
    assert s.key_source == "keyring"


def test_no_key_anywhere_is_fail_closed(tmp_path, monkeypatch):
    import vii.keystore as ks
    monkeypatch.setattr(ks, "load_api_key", lambda d: "")
    s = _settings(tmp_path, MODEL_API_KEY="")
    assert s.has_api_key is False
    assert s.live_mode is False
    assert s.key_source == "none"


# -- readiness tiers -----------------------------------------------------------

def test_readiness_distinguishes_four_tiers(tmp_path, monkeypatch):
    import vii.keystore as ks
    monkeypatch.setattr(ks, "load_api_key", lambda d: "")
    from vii.providers.capabilities import readiness_report
    r = readiness_report(_settings(tmp_path, MODEL_API_KEY=""))
    assert r["local_ingestion"]["status"] == "ready"
    assert r["demo"]["status"] == "available_opt_in"
    assert r["provider_configuration"]["status"] == "blocked"
    assert r["live_verification"]["status"] == "not_verified"
    r2 = readiness_report(_settings(tmp_path, MODEL_API_KEY="k"))
    assert r2["provider_configuration"]["status"] == "configured_unverified"
    assert r2["live_verification"]["status"] == "not_verified"


# -- safe connection test (fake transport only) --------------------------------

def test_connection_test_classifies_without_leaking_key():
    from vii.cli import test_connection

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = "body"

    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization", "")
        return _Resp(fake_get.code)

    fake_get.code = 200
    out = test_connection("https://api.example/v1", "test-key-not-real",
                          get=fake_get)
    assert out["ok"] is True
    assert "test-key-not-real" not in str(out)
    assert seen["url"].endswith("/models")
    fake_get.code = 401
    out = test_connection("https://api.example/v1", "bad", get=fake_get)
    assert out["ok"] is False and "rejected" in out["message"]


# -- terminal credential management ---------------------------------------------

def test_cli_credentials_status_shows_source_not_secret(tmp_path, capsys,
                                                          monkeypatch):
    import vii.keystore as ks
    monkeypatch.setattr(ks, "load_api_key", lambda d: "")
    from vii import cli
    code = cli.main(["credentials", "status"],
                    settings=_settings(tmp_path, MODEL_API_KEY="env-secret-123"))
    out = capsys.readouterr().out
    assert code == 0
    assert "env-secret-123" not in out
    assert "env" in out  # source shown, never the value
    assert "consumer" in out.lower()  # provider vs consumer distinction


def test_cli_credentials_set_and_remove_via_keystore(tmp_path, capsys,
                                                       monkeypatch):
    import vii.keystore as ks
    store = {}
    monkeypatch.setattr(ks, "store_api_key",
                        lambda k, d: store.update(key=k) or "keyring")
    monkeypatch.setattr(ks, "load_api_key", lambda d: store.get("key", ""))
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "new-secret-456")
    from vii import cli
    assert cli.main(["credentials", "set"],
                    settings=_settings(tmp_path, MODEL_API_KEY="")) == 0
    assert store["key"] == "new-secret-456"
    assert "new-secret-456" not in capsys.readouterr().out
    assert cli.main(["credentials", "remove"],
                    settings=_settings(tmp_path, MODEL_API_KEY="")) == 0
    assert store["key"] == ""
