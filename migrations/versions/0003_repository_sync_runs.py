"""repository_sync_runs — sync run lifecycle tracking

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_sync_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_objects_processed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "documents_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "versions_created",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "versions_skipped",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["external_repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repository_sync_runs_repository_id_created_at",
        "repository_sync_runs",
        ["repository_id", "created_at"],
    )
    op.create_index(
        "ix_repository_sync_runs_repository_id_status",
        "repository_sync_runs",
        ["repository_id", "status"],
    )
    op.create_index(
        "ix_repository_sync_runs_connector_id",
        "repository_sync_runs",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_sync_runs_connector_id", "repository_sync_runs")
    op.drop_index("ix_repository_sync_runs_repository_id_status", "repository_sync_runs")
    op.drop_index("ix_repository_sync_runs_repository_id_created_at", "repository_sync_runs")
    op.drop_table("repository_sync_runs")
