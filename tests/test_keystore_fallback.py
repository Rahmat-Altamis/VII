"""Keystore fallback regression tests (synthetic keys only, tmp dirs only).

Regression: src/vii/keystore.py previously had a mis-indented
``except OSError:`` under ``try: fp.chmod(0o600)``, making the whole
module unparsable. These tests pin the intended fallback behavior:
a failing/unavailable keyring falls back to a 0600 JSON file under the
data dir, and a chmod failure never masks that return value.
Never touches a real keyring backend or real credentials.
"""
import json
import stat
import sys
import types
from pathlib import Path

from vii.keystore import load_api_key, store_api_key

SYNTHETIC_KEY = "synthetic-test-key-not-real"


class _FailingKeyring(types.SimpleNamespace):
    def __init__(self):
        super().__init__(
            set_password=lambda *a: (_ for _ in ()).throw(RuntimeError("keyring unavailable")),
            get_password=lambda *a: (_ for _ in ()).throw(RuntimeError("keyring unavailable")),
            delete_password=lambda *a: (_ for _ in ()).throw(RuntimeError("keyring unavailable")),
        )


class _WorkingKeyring(types.SimpleNamespace):
    def __init__(self):
        store = {}
        super().__init__(
            set_password=lambda svc, acct, val: store.__setitem__((svc, acct), val),
            get_password=lambda svc, acct: store.get((svc, acct)),
            delete_password=lambda svc, acct: store.pop((svc, acct), None),
        )


def test_failing_keyring_falls_back_to_0600_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", _FailingKeyring())
    result = store_api_key(SYNTHETIC_KEY, tmp_path)
    assert result.startswith("fallback-file")
    fp = tmp_path / ".keyring-fallback.json"
    assert fp.exists()
    assert stat.S_IMODE(fp.stat().st_mode) == 0o600
    assert json.loads(fp.read_text()) == {"meta_api_key": SYNTHETIC_KEY}
    assert load_api_key(tmp_path) == SYNTHETIC_KEY


def test_chmod_failure_still_returns_fallback(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", _FailingKeyring())
    real_chmod = Path.chmod

    def flaky_chmod(self, mode, *args, **kwargs):
        if self.name == ".keyring-fallback.json":
            raise OSError("chmod not supported on this filesystem")
        return real_chmod(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", flaky_chmod)
    result = store_api_key(SYNTHETIC_KEY, tmp_path)
    assert result.startswith("fallback-file")
    assert json.loads((tmp_path / ".keyring-fallback.json").read_text()) == {
        "meta_api_key": SYNTHETIC_KEY}


def test_working_keyring_is_preferred_and_no_fallback_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", _WorkingKeyring())
    assert store_api_key(SYNTHETIC_KEY, tmp_path) == "keyring"
    assert load_api_key(tmp_path) == SYNTHETIC_KEY
    assert not (tmp_path / ".keyring-fallback.json").exists()
