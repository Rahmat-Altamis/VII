"""Add evidence_sources.relationship and .publication_date (SQLite + PG)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_evidence_relationship"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence_sources") as b:
        b.add_column(sa.Column("relationship", sa.String(32),
                               nullable=False, server_default=""))
        b.add_column(sa.Column("publication_date", sa.String(64),
                               nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("evidence_sources") as b:
        b.drop_column("publication_date")
        b.drop_column("relationship")
