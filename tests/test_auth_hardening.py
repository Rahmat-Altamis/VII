"""Phase 1: production authentication hardening.

Loopback-only unauthenticated dev, non-loopback rejection, key validation,
stable identity (explicit mapping + full-SHA-256 fallback), no key leakage,
and X-Consumer spoof resistance when auth is enabled.
"""
import hashlib

import pytest

from vii.config import Settings, _is_loopback_host


def _s(**kw):
    kw.setdefault("VII_API_HOST", "127.0.0.1")
    kw.setdefault("VII_STORAGE_DIR", "/tmp/vii_auth_tests")
    return Settings(**kw)


# -- loopback classification --------------------------------------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1",
                                  "127.1", "127.0.0.2", "[::1]"])
def test_loopback_accepted_unauthed(host):
    s = _s(VII_API_HOST=host)
    assert not s.require_auth  # construction itself must not raise


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5",
                                   "8.8.8.8", "example.com", "", " ", "my-server"])
def test_non_loopback_rejected_unauthed(host):
    with pytest.raises(ValueError, match="not loopback"):
        _s(VII_API_HOST=host)


def test_is_loopback_host_unit():
    assert _is_loopback_host("127.0.0.1") and _is_loopback_host("::1")
    assert _is_loopback_host("localhost")
    assert not _is_loopback_host("0.0.0.0") and not _is_loopback_host("::")
    assert not _is_loopback_host("example.com") and not _is_loopback_host("")


def test_non_loopback_with_auth_and_keys_accepted():
    s = _s(VII_API_HOST="0.0.0.0", VII_REQUIRE_AUTH=True,
           VII_API_KEYS="sekret-1,sekret-2")
    assert s.require_auth and len(s.valid_api_keys()) == 2


def test_require_auth_without_keys_rejected():
    with pytest.raises(ValueError, match="VII_API_KEYS or VII_CONSUMER_KEYS"):
        _s(VII_REQUIRE_AUTH=True)
    with pytest.raises(ValueError, match="VII_API_KEYS or VII_CONSUMER_KEYS"):
        _s(VII_REQUIRE_AUTH=True, VII_CONSUMER_KEYS=" , ,")
    # malformed consumer mappings alone must NOT satisfy production validation
    with pytest.raises(ValueError, match="VII_API_KEYS or VII_CONSUMER_KEYS"):
        _s(VII_REQUIRE_AUTH=True, VII_CONSUMER_KEYS="no-colon-here,,:,")


def test_consumer_keys_alone_satisfy_production_validation():
    s = _s(VII_API_HOST="0.0.0.0", VII_REQUIRE_AUTH=True,
           VII_CONSUMER_KEYS="alice:key-alice")
    assert s.require_auth


# -- credential checks ---------------------------------------------------------
def test_missing_and_invalid_credentials_rejected():
    s = _s(VII_REQUIRE_AUTH=True, VII_API_KEYS="good-key")
    assert s.check_api_key("") == (False, "")
    assert s.check_api_key("wrong-key") == (False, "")
    assert s.check_api_key(" good-key ") == (False, "")  # no silent trimming inside


def test_consumer_keys_mapping_identity():
    s = _s(VII_REQUIRE_AUTH=True, VII_CONSUMER_KEYS="alice:key-alice,bob:key-bob")
    assert s.check_api_key("key-alice") == (True, "alice")
    assert s.check_api_key("key-bob") == (True, "bob")
    assert s.check_api_key("key-carol") == (False, "")


def test_malformed_consumer_map_entries_ignored():
    s = _s(VII_REQUIRE_AUTH=True, VII_API_KEYS="real",
           VII_CONSUMER_KEYS="nope,,:nokey,novalue:,: both-empty ,ok:real")
    m = s.consumer_key_map()
    assert m == {"real": "ok"}
    # explicit mapping wins over the bare VII_API_KEYS entry for the same key
    assert s.check_api_key("real") == (True, "ok")


def test_full_sha256_fallback_identity_stable():
    kw = dict(VII_REQUIRE_AUTH=True, VII_API_KEYS="stable-key-1")
    a = _s(**kw).check_api_key("stable-key-1")
    b = _s(**kw).check_api_key("stable-key-1")  # new Settings = new process
    expected = "key-" + hashlib.sha256(b"stable-key-1").hexdigest()
    assert a == (True, expected) == b
    assert len(expected) == 4 + 64  # full digest, not truncated


def test_redacted_never_exposes_keys():
    raw_key = "super-secret-key-xyz"
    raw_map = "alice:map-secret-abc,bob:map-secret-def"
    s = _s(VII_REQUIRE_AUTH=True, MODEL_API_KEY=raw_key,
           VII_API_KEYS=raw_key, VII_CONSUMER_KEYS=raw_map)
    blob = str(s.redacted())
    for secret in (raw_key, "map-secret-abc", "map-secret-def", raw_map):
        assert secret not in blob
    assert "alice" not in blob and "bob" not in blob
    # counts still visible for operators
    assert "1 configured" in blob and "2 consumer mapping(s)" in blob


def test_unauthenticated_dev_uses_configured_consumer():
    s = _s(VII_CONSUMER_ID="devbox")
    assert s.check_api_key("anything") == (True, "devbox")


# -- HTTP-level: X-Consumer spoof resistance + missing/invalid creds ------------
def _client_with(settings):
    import vii.api.v1 as v1
    from fastapi.testclient import TestClient
    from vii.api.app import app
    from vii.application.services import AnalysisService
    from vii.config import get_settings
    get_settings.cache_clear()
    import os
    for k, v in {"VII_REQUIRE_AUTH": "true",
                 "VII_API_KEYS": "svc-key-1",
                 "VII_CONSUMER_KEYS": "alice:alice-key",
                 "VII_OFFLINE_MODE": "true",
                 "VII_DATABASE_URL": f"sqlite:///{settings.storage_dir}/vii.db",
                 "VII_STORAGE_DIR": str(settings.storage_dir)}.items():
        os.environ[k] = v
    get_settings.cache_clear()
    v1._service = AnalysisService(get_settings())
    return TestClient(app, raise_server_exceptions=False)


def test_http_missing_invalid_and_spoof(tmp_path):
    from vii.config import Settings as S
    s = S(VII_OFFLINE_MODE=True,
          VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
          VII_STORAGE_DIR=tmp_path)
    c = _client_with(s)
    try:
        r = c.get("/v1/diagnostics")
        assert r.status_code == 401  # no credentials at all
        r = c.get("/v1/diagnostics", headers={"X-Consumer": "alice"})
        assert r.status_code == 401  # X-Consumer alone authenticates nobody
        r = c.get("/v1/diagnostics", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 403
        r = c.get("/v1/diagnostics", headers={"Authorization": "Bearer alice-key"})
        assert r.status_code == 200  # mapped identity works
        r = c.get("/v1/diagnostics", headers={"Authorization": "Bearer svc-key-1"})
        assert r.status_code == 200  # bare key with digest identity works
        # spoof attempt: valid key for svc-key-1 + forged X-Consumer header
        r = c.get("/v1/datasets/search",
                  headers={"Authorization": "Bearer svc-key-1",
                           "X-Consumer": "alice"})
        assert r.status_code == 200
        assert r.json() == []  # key identity has no samples; alice's are invisible
    finally:
        import os
        for k in ("VII_REQUIRE_AUTH", "VII_API_KEYS", "VII_CONSUMER_KEYS",
                  "VII_OFFLINE_MODE", "VII_DATABASE_URL", "VII_STORAGE_DIR"):
            os.environ.pop(k, None)
        from vii.config import get_settings
        get_settings.cache_clear()
