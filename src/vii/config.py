"""Application configuration (env-driven, secrets never logged)."""
from __future__ import annotations

import hashlib
import ipaddress
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_loopback_host(host: str) -> bool:
    """True only for loopback bind targets. IPv4 numeric shorthands
    ('127.1', '2130706433') resolve via inet_aton without DNS. Fail closed:
    unparseable hostnames and non-IP names (other than localhost) count as
    non-loopback, so unauthenticated mode can never bind a public interface
    by accident."""
    import socket
    import struct
    h = (host or "").strip().lower().strip("[]")
    if h in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        pass
    if h and all(c.isdigit() or c == "." for c in h):
        try:
            packed = socket.inet_aton(h)
            return ipaddress.ip_address(struct.unpack("!I", packed)[0]).is_loopback
        except (OSError, struct.error):
            return False
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_api_key: str = Field(default="", alias="MODEL_API_KEY")
    meta_base_url: str = Field(default="https://api.meta.ai/v1", alias="META_BASE_URL")
    meta_model: str = Field(default="muse-spark-1.3", alias="META_MODEL")
    meta_transcription_model: str = Field(
        default="muse-voice-transcribe-1.0", alias="META_TRANSCRIPTION_MODEL"
    )
    # Explicit synthetic-demo opt-in only. VII is online-first: demo mode is
    # never a fallback for a missing key or a failed provider request.
    demo_mode: bool = Field(default=False, alias="VII_DEMO_MODE")
    # Deprecated alias for demo_mode (kept so existing .env files keep working).
    offline_mode: bool = Field(default=False, alias="VII_OFFLINE_MODE")
    database_url: str = Field(default="sqlite:///./data/vii.db", alias="VII_DATABASE_URL")
    storage_dir: Path = Field(default=Path("./data"), alias="VII_STORAGE_DIR")
    max_upload_mb: int = Field(default=512, alias="VII_MAX_UPLOAD_MB")
    max_video_seconds: int = Field(default=3600, alias="VII_MAX_VIDEO_SECONDS")
    ffmpeg_bin: str = Field(default="ffmpeg", alias="VII_FFMPEG_BIN")
    ffprobe_bin: str = Field(default="ffprobe", alias="VII_FFPROBE_BIN")
    search_context_size: str = Field(default="medium", alias="VII_SEARCH_CONTEXT_SIZE")
    api_host: str = Field(default="127.0.0.1", alias="VII_API_HOST")
    api_port: int = Field(default=8765, alias="VII_API_PORT")
    instagram_token: str = Field(default="", alias="VII_INSTAGRAM_TOKEN")
    facebook_page_token: str = Field(default="", alias="VII_FACEBOOK_PAGE_TOKEN")
    api_keys: str = Field(default="", alias="VII_API_KEYS")  # comma-separated service keys
    consumer_id: str = Field(default="default", alias="VII_CONSUMER_ID")
    storage_backend: str = Field(default="local", alias="VII_STORAGE_BACKEND")
    s3_bucket: str = Field(default="", alias="VII_S3_BUCKET")
    s3_endpoint: str = Field(default="", alias="VII_S3_ENDPOINT")
    worker_concurrency: int = Field(default=2, alias="VII_WORKER_CONCURRENCY")
    require_auth: bool = Field(default=False, alias="VII_REQUIRE_AUTH")
    webhook_enabled: bool = Field(default=False, alias="VII_WEBHOOK_ENABLED")
    # Dataset CSV: canonical default is data/dataset.csv. The app never
    # requires it at startup and never auto-starts analysis from it; see
    # vii.dataset.ingestion and docs/DATASET.md. DATASET_CSV_PATH overrides.
    dataset_csv_path: Path = Field(default=Path("data/dataset.csv"),
                                   alias="DATASET_CSV_PATH")
    request_timeout_s: float = 120.0
    max_retries: int = 2
    # Stage gates. Transcription is a separate provider path (FFmpeg audio
    # extraction + transcription model); it is only needed when the chosen
    # video-understanding path does not already cover audio. Default keeps
    # historical behaviour for local files.
    enable_transcription: bool = Field(default=True, alias="VII_ENABLE_TRANSCRIPTION")
    # Visual perception: disabled by default. Providers: ``local``
    # (working frame analysis) and ``sam`` (SAM 3.1 adapter implemented
    # against the docs-verified contract; same key as MODEL_API_KEY
    # unless VII_SAM_API_KEY overrides it). Enabling this alone never
    # fabricates results — see vii.providers.visual.
    enable_visual_perception: bool = Field(
        default=False, alias="VII_ENABLE_VISUAL_PERCEPTION")
    visual_perception_provider: str = Field(
        default="", alias="VII_VISUAL_PERCEPTION_PROVIDER")
    sam_api_key: str = Field(default="", alias="VII_SAM_API_KEY")
    sam_model: str = Field(default="", alias="VII_SAM_MODEL")

    consumer_keys: str = Field(default="", alias="VII_CONSUMER_KEYS")
    # Explicit mapping "consumer-name:service-key,..." — preferred identity
    # source. Keys never appear in logs; only the consumer name is stored.

    def has_configured_keys(self) -> bool:
        """True when at least one usable service key exists — a non-empty
        VII_API_KEYS entry or a well-formed VII_CONSUMER_KEYS 'name:key'
        mapping. Whitespace/comma/malformed-only values count as none."""
        return bool(self.valid_api_keys() or self.consumer_key_map())

    @model_validator(mode="after")
    def _production_guards(self):
        # Authenticated deployments must actually configure service keys;
        # silent unauthenticated production modes are a tenant-isolation hole.
        if self.require_auth and not self.has_configured_keys():
            raise ValueError("VII_REQUIRE_AUTH=true requires VII_API_KEYS or VII_CONSUMER_KEYS to be set")
        # Binding a non-loopback interface without authentication exposes every
        # consumer's jobs/reports/datasets. Local unauthenticated dev is only
        # allowed on loopback; anything else must set VII_REQUIRE_AUTH=true
        # with keys configured.
        if not self.require_auth and not _is_loopback_host(self.api_host):
            raise ValueError(
                f"VII_API_HOST={self.api_host!r} is not loopback: refusing to run "
                "unauthenticated. Set VII_REQUIRE_AUTH=true with VII_API_KEYS, or "
                "bind 127.0.0.1 / localhost / ::1 for local development."
            )
        return self

    @property
    def effective_api_key(self) -> str:
        """Env MODEL_API_KEY first, OS keyring second, '' when neither is set.

        Uses vii.keystore (OS keyring with a 0600-file fallback under storage_dir),
        so a key saved from Settings survives restarts without touching .env.
        """
        if self.model_api_key.strip():
            return self.model_api_key.strip()
        try:
            from vii.keystore import load_api_key

            return load_api_key(self.storage_dir) or ""
        except Exception:
            return ""

    @property
    def key_source(self) -> str:
        if self.model_api_key.strip():
            return "env"
        try:
            from vii.keystore import load_api_key

            return "keyring" if load_api_key(self.storage_dir) else "none"
        except Exception:
            return "none"

    @property
    def has_api_key(self) -> bool:
        return bool(self.effective_api_key)

    @property
    def demo_enabled(self) -> bool:
        """True only when synthetic demo mode was explicitly opted into
        (VII_DEMO_MODE, or the deprecated VII_OFFLINE_MODE alias)."""
        return bool(self.demo_mode or self.offline_mode)

    @property
    def live_mode(self) -> bool:
        """True only when online mode is allowed AND a key is configured."""
        return not self.demo_enabled and self.has_api_key

    def redacted(self) -> dict:
        d = self.model_dump()
        d["model_api_key"] = f"*** ({self.key_source})" if self.has_api_key else "(not set)"
        for k in ("instagram_token", "facebook_page_token", "sam_api_key"):
            d[k] = "*** (set)" if d.get(k) else "(not set)"
        d["api_keys"] = f"*** ({len(self.valid_api_keys())} configured)" if self.api_keys else "(not set)"
        n_map = len(self.consumer_key_map())
        d["consumer_keys"] = (f"*** ({n_map} consumer mapping(s))" if self.consumer_keys.strip()
                              else "(not set)")
        return d

    def valid_api_keys(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    def consumer_key_map(self) -> dict[str, str]:
        """Parse VII_CONSUMER_KEYS 'name:key,...' into {key: name}.

        Malformed entries (no colon, empty name or key) are skipped — they
        must never authenticate anyone. Values never enter logs.
        """
        out: dict[str, str] = {}
        for entry in self.consumer_keys.split(","):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue
            name, _, key = entry.partition(":")
            name, key = name.strip(), key.strip()
            if name and key and key not in out:
                out[key] = name[:128]
        return out

    def check_api_key(self, provided: str) -> tuple[bool, str]:
        """Authenticate a consumer. Returns (ok, consumer_id).

        Identity resolution: explicit VII_CONSUMER_KEYS mapping first
        (stable, operator-assigned names), else the full SHA-256 hex digest
        of the key material prefixed 'key-'. The full 64-hex digest
        preserves ~256-bit collision resistance, is stable across restarts
        in every process, and the raw key never appears in logs or stored
        records. See redacted(): only configuration counts are exposed.
        """
        if not self.require_auth:
            return True, self.consumer_id or "default"
        if not provided:
            return False, ""
        mapped = self.consumer_key_map().get(provided)
        if mapped:
            return True, mapped
        if provided in self.valid_api_keys():
            return True, f"key-{hashlib.sha256(provided.encode()).hexdigest()}"
        return False, ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
