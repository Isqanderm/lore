"""repository_artifacts — deterministic brief artifacts per repository

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_sync_run_id", sa.UUID(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "artifact_type IN ('repository_brief')",
            name="ck_repository_artifact_type",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["external_repositories.id"],
            name="fk_repository_artifacts_repository_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_sync_run_id"],
            ["repository_sync_runs.id"],
            name="fk_repository_artifacts_source_sync_run_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "artifact_type", name="uq_repository_artifact_type"),
    )
    op.create_index(
        "ix_repository_artifacts_repository_id",
        "repository_artifacts",
        ["repository_id"],
    )
    op.create_index(
        "ix_repository_artifacts_artifact_type",
        "repository_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        "ix_repository_artifacts_source_sync_run_id",
        "repository_artifacts",
        ["source_sync_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_artifacts_source_sync_run_id", "repository_artifacts")
    op.drop_index("ix_repository_artifacts_artifact_type", "repository_artifacts")
    op.drop_index("ix_repository_artifacts_repository_id", "repository_artifacts")
    op.drop_table("repository_artifacts")
