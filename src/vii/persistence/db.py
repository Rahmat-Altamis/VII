"""Engine/session helpers + table creation. Alembic handles migrations; create_all for zero-config."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vii.persistence.models import Base


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
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
