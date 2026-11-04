"""Engine/session helpers + table creation. Alembic handles migrations; create_all for zero-config."""
from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vii.persistence.models import Base

_INIT_LOCK = threading.Lock()


def make_engine(db_url: str):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args, future=True)


def init_db(db_url: str, storage_dir: str | Path = "./data"):
    if db_url.startswith("sqlite"):
        path = db_url.split("sqlite:///")[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_url)
    with _INIT_LOCK:
        # create_all checkfirst still races across threads and processes
        # on a fresh file, so a lost race is retried as a verify, never
        # surfaced. Any other error still raises.
        try:
            Base.metadata.create_all(engine)
        except Exception as e:  # noqa: BLE001
            if "already exists" not in str(e).lower():
                raise
            Base.metadata.create_all(engine)
        if db_url.startswith("sqlite"):
            # create_all does not alter existing tables; migrate() upgrades
            # old databases to the current schema idempotently. Inside the
            # lock so concurrent first runs cannot double apply a version.
            from vii.persistence.migrations import migrate

            migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
