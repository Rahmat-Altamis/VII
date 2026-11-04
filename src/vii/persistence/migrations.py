"""Idempotent startup migrations for existing VII databases.

`Base.metadata.create_all()` creates missing tables but never alters
existing ones, so databases created before a schema change stay broken
(the Phase 1 `evidence_sources.relationship` / `publication_date`
drift). `migrate()` closes that gap: it inspects the live schema, adds
genuinely missing columns without touching rows, and records each
applied version in `vii_schema_migrations`. Safe to call on every
startup; a version is recorded only after its upgrade succeeds, so a
failed run retried later resumes cleanly. Alembic revisions remain the
managed-DB path (see alembic/versions/0002_*).
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

log = logging.getLogger("vii.persistence.migrations")


def _columns(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)} if insp.has_table(table) else set()


def _upgrade_0002_evidence_relationship(conn, insp) -> None:
    cols = _columns(insp, "evidence_sources")
    if not cols:
        return  # fresh DB: create_all already built the new table
    if "relationship" not in cols:
        conn.execute(text("ALTER TABLE evidence_sources "
                          "ADD COLUMN relationship VARCHAR(32) DEFAULT ''"))
    if "publication_date" not in cols:
        conn.execute(text("ALTER TABLE evidence_sources "
                          "ADD COLUMN publication_date VARCHAR(64) DEFAULT ''"))


MIGRATIONS: list[tuple[str, object]] = [
    ("0002_evidence_relationship_publication_date",
     _upgrade_0002_evidence_relationship),
]


def migrate(engine) -> list[str]:
    """Apply pending migrations; returns versions applied this call."""
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS vii_schema_migrations "
                          "(version VARCHAR(128) PRIMARY KEY, "
                          "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        done = {r[0] for r in conn.execute(
            text("SELECT version FROM vii_schema_migrations"))}
        insp = inspect(conn)
        for version, upgrade in MIGRATIONS:
            if version in done:
                continue
            upgrade(conn, insp)  # type: ignore[operator]
            conn.execute(text("INSERT INTO vii_schema_migrations (version) "
                              "VALUES (:v)"), {"v": version})
            applied.append(version)
            log.info("applied DB migration %s", version)
    return applied
