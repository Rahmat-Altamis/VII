import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from vii.config import Settings  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    # Explicit synthetic-demo opt-in: fixture pipeline only, never a fallback.
    return Settings(_env_file=None, VII_DEMO_MODE=True,
                    VII_DATABASE_URL=f"sqlite:///{tmp_path}/vii.db",
                    VII_STORAGE_DIR=tmp_path)
