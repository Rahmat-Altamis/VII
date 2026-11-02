"""Storage abstraction: local filesystem default, S3-compatible backend.

Separates originals / derived / tmp / frames / audio / fingerprints /
reports. Prod uses Postgres + S3; dev uses SQLite + local dir. No cloud
credentials are required for local development.
"""
from __future__ import annotations

from pathlib import Path

LAYOUT = ("originals", "derived", "tmp", "frames", "audio",
          "fingerprints", "reports", "datasets", "corpus", "media", "exports")


class LocalStorage:
    """Filesystem backend rooted at storage_dir."""

    kind = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        for sub in LAYOUT:
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def path(self, area: str, name: str) -> Path:
        if area not in LAYOUT:
            raise ValueError(f"unknown storage area: {area}")
        return self.root / area / name

    def put_bytes(self, area: str, name: str, data: bytes) -> Path:
        p = self.path(area, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def get_bytes(self, area: str, name: str) -> bytes:
        return self.path(area, name).read_bytes()

    def exists(self, area: str, name: str) -> bool:
        return self.path(area, name).exists()


class S3Storage:
    """S3-compatible backend interface (lazy boto3; local dev never requires it)."""

    kind = "s3"

    def __init__(self, bucket: str, endpoint: str = "", prefix: str = "vii/"):
        if not bucket:
            raise ValueError("VII_S3_BUCKET is required for the s3 storage backend")
        self.bucket = bucket
        self.endpoint = endpoint or None
        self.prefix = prefix
        self._client = None

    def _sdk(self):
        if self._client is None:
            import boto3  # lazy: keeps local installs dependency-free
            kw: dict = {}
            if self.endpoint:
                kw["endpoint_url"] = self.endpoint
            self._client = boto3.client("s3", **kw)
        return self._client

    def _key(self, area: str, name: str) -> str:
        if area not in LAYOUT:
            raise ValueError(f"unknown storage area: {area}")
        return f"{self.prefix}{area}/{name}"

    def put_bytes(self, area: str, name: str, data: bytes) -> str:
        self._sdk().put_object(Bucket=self.bucket, Key=self._key(area, name), Body=data)
        return f"s3://{self.bucket}/{self._key(area, name)}"

    def get_bytes(self, area: str, name: str) -> bytes:
        resp = self._sdk().get_object(Bucket=self.bucket, Key=self._key(area, name))
        return resp["Body"].read()

    def exists(self, area: str, name: str) -> bool:
        try:
            self._sdk().head_object(Bucket=self.bucket, Key=self._key(area, name))
            return True
        except Exception:
            return False


def get_storage(settings) -> LocalStorage | S3Storage:
    backend = (settings.storage_backend or "local").lower()
    if backend == "s3":
        return S3Storage(settings.s3_bucket, settings.s3_endpoint)
    return LocalStorage(settings.storage_dir)
