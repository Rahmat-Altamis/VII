"""Initial VII schema (persistence.models, revision 0001).

Creates all 12 tables exactly as defined in vii.persistence.models:
analysis_jobs, video_sources, meta_requests, claims, evidence_sources,
citations, claim_assessments, transcript_segments, search_sessions,
processing_logs, reports, dataset_samples.

Downgrade drops them in reverse dependency order. SQLite and PostgreSQL
compatible (String/Text/DateTime/Float/Integer only).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column("consumer", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("source_ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("acquisition_method", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("offline", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "video_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), sa.ForeignKey("analysis_jobs.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "meta_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("purpose", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("request_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("response_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("offline", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), sa.ForeignKey("analysis_jobs.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="factual"),
        sa.Column("start_s", sa.Float(), nullable=True),
        sa.Column("end_s", sa.Float(), nullable=True),
    )
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("claim_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("publisher", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("method", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("search_response_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("claim_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("cited_span", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("end_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_response_id", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_table(
        "claim_assessments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("claim_id", sa.String(length=64), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("excerpts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("contradictions", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("limitations", sa.Text(), nullable=False, server_default=""),
        sa.Column("method", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("start_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("end_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("speaker", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("engine", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_table(
        "search_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("claim_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("offline", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "processing_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="json"),
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "dataset_samples",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("consumer", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("video_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("platform", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("storage_ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("duration_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("fingerprint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("annotation_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("labels_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "dataset_samples", "reports", "processing_logs", "search_sessions",
        "transcript_segments", "claim_assessments", "citations",
        "evidence_sources", "claims", "meta_requests", "video_sources",
        "analysis_jobs",
    ):
        op.drop_table(table)
