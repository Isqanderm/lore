# migrations/versions/0005_document_active_state.py
"""document_active_state — soft-delete and sync tracking for documents

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "first_seen_sync_run_id",
            sa.UUID(),
            sa.ForeignKey(
                "repository_sync_runs.id",
                name="fk_documents_first_seen_sync_run_id",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_seen_sync_run_id",
            sa.UUID(),
            sa.ForeignKey(
                "repository_sync_runs.id",
                name="fk_documents_last_seen_sync_run_id",
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_is_active", "documents", ["is_active"])
    op.create_index(
        "ix_documents_first_seen_sync_run_id",
        "documents",
        ["first_seen_sync_run_id"],
    )
    op.create_index(
        "ix_documents_last_seen_sync_run_id",
        "documents",
        ["last_seen_sync_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_last_seen_sync_run_id", "documents")
    op.drop_index("ix_documents_first_seen_sync_run_id", "documents")
    op.drop_index("ix_documents_is_active", "documents")
    op.drop_column("documents", "last_seen_sync_run_id")
    op.drop_column("documents", "first_seen_sync_run_id")
    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "is_active")
