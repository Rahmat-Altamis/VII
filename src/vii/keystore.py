"""Secure credential storage: OS keyring when available, documented fallback."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SERVICE = "video-integrity-intelligence"
ACCOUNT = "meta-api-key"


def _fallback_file(data_dir: Path) -> Path:
    return Path(data_dir) / ".keyring-fallback.json"


def _write_fallback(data_dir: Path, api_key: str) -> None:
    fp = _fallback_file(data_dir)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=fp.parent, prefix=".keyring-fallback-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"meta_api_key": api_key}))
        os.replace(tmp, fp)
        try:
            fp.chmod(0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store_api_key(api_key: str, data_dir: Path) -> str:
    """Returns 'keyring' or 'fallback-file (0600)'. Empty key clears stored value.

    The write is verified by reading back: a backend that silently discards
    the secret (e.g. a null/disabled keyring) falls through to the 0600-file
    fallback instead of reporting a success that load_api_key cannot honor.
    Clearing removes both the keyring entry and any fallback file.
    """
    if not api_key:
        try:
            import keyring  # type: ignore[import]

            try:
                keyring.delete_password(SERVICE, ACCOUNT)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        _fallback_file(data_dir).unlink(missing_ok=True)
        return "keyring"
    try:
        import keyring  # type: ignore[import]

        keyring.set_password(SERVICE, ACCOUNT, api_key)
        if keyring.get_password(SERVICE, ACCOUNT) == api_key:
            _fallback_file(data_dir).unlink(missing_ok=True)
            return "keyring"
    except Exception:  # noqa: BLE001
        pass
    _write_fallback(data_dir, api_key)
    return "fallback-file (mode 0600, VII_DATA_DIR/.keyring-fallback.json)"


def load_api_key(data_dir: Path) -> str:
    """Keyring first; a missing/empty keyring entry falls back to the file."""
    try:
        import keyring  # type: ignore[import]

        value = keyring.get_password(SERVICE, ACCOUNT)
        if value:
            return value
    except Exception:  # noqa: BLE001
        pass
    fp = _fallback_file(data_dir)
    if fp.exists():
        try:
            return json.loads(fp.read_text()).get("meta_api_key", "") or ""
        except (json.JSONDecodeError, OSError):
            return ""
    return ""
