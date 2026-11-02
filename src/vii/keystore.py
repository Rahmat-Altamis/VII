"""Secure credential storage: OS keyring when available, documented fallback."""
from __future__ import annotations

import json
from pathlib import Path

SERVICE = "video-integrity-intelligence"
ACCOUNT = "meta-api-key"


def _fallback_file(data_dir: Path) -> Path:
    return Path(data_dir) / ".keyring-fallback.json"


def store_api_key(api_key: str, data_dir: Path) -> str:
    """Returns 'keyring' or 'fallback-file (0600)'. Empty key clears stored value.

    The write is verified by reading back: a backend that silently discards
    the secret (e.g. a null/disabled keyring) falls through to the 0600-file
    fallback instead of reporting a success that load_api_key cannot honor.
    """
    try:
        import keyring  # type: ignore[import]

        if api_key:
            keyring.set_password(SERVICE, ACCOUNT, api_key)
            if keyring.get_password(SERVICE, ACCOUNT) == api_key:
                return "keyring"
        else:
            try:
                keyring.delete_password(SERVICE, ACCOUNT)
            except Exception:  # noqa: BLE001
                pass
            return "keyring"
    except Exception:  # noqa: BLE001
        pass
    fp = _fallback_file(data_dir)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps({"meta_api_key": api_key}))
    try:
        fp.chmod(0o600)
    except OSError:
        pass
    return "fallback-file (mode 0600, VII_DATA_DIR/.keyring-fallback.json)"


def load_api_key(data_dir: Path) -> str:
    try:
        import keyring  # type: ignore[import]

        return keyring.get_password(SERVICE, ACCOUNT) or ""
    except Exception:  # noqa: BLE001
        fp = _fallback_file(data_dir)
        if fp.exists():
            try:
                return json.loads(fp.read_text()).get("meta_api_key", "")
            except (json.JSONDecodeError, OSError):
                return ""
        return ""
