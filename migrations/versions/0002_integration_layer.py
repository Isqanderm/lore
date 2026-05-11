"""integration layer — external_connections, external_repositories, external_objects

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("external_account_id", sa.Text(), nullable=True),
        sa.Column("installation_id", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "external_repositories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["connection_id"], ["external_connections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_repositories_provider_full_name",
        "external_repositories",
        ["provider", "full_name"],
    )

    op.create_table(
        "external_objects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=True),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column(
            "raw_payload_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["external_connections.id"]),
        sa.ForeignKeyConstraint(["repository_id"], ["external_repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider",
            "external_id",
            name="uq_external_objects_connection_provider_id",
        ),
    )
    op.create_index(
        "ix_external_objects_repository_id",
        "external_objects",
        ["repository_id"],
    )
    op.create_index(
        "ix_external_objects_provider_object_type",
        "external_objects",
        ["provider", "object_type"],
    )

    # Evolve existing tables (all nullable — no breaking change)
    op.add_column(
        "sources",
        sa.Column("external_object_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sources_external_object_id",
        "sources",
        "external_objects",
        ["external_object_id"],
        ["id"],
    )
    op.create_index("ix_sources_external_object_id", "sources", ["external_object_id"])

    op.add_column("documents", sa.Column("document_kind", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("logical_path", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_documents_document_kind", "documents", ["document_kind"])
    op.create_index("ix_documents_logical_path", "documents", ["logical_path"])

    op.add_column("document_versions", sa.Column("version_ref", sa.Text(), nullable=True))
    op.add_column(
        "document_versions",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_document_versions_content_hash", "document_versions", ["checksum"])
    op.create_index("ix_document_versions_version_ref", "document_versions", ["version_ref"])


def downgrade() -> None:
    op.drop_index("ix_document_versions_version_ref", "document_versions")
    op.drop_index("ix_document_versions_content_hash", "document_versions")
    op.drop_column("document_versions", "metadata")
    op.drop_column("document_versions", "source_updated_at")
    op.drop_column("document_versions", "version_ref")

    op.drop_index("ix_documents_logical_path", "documents")
    op.drop_index("ix_documents_document_kind", "documents")
    op.drop_column("documents", "metadata")
    op.drop_column("documents", "logical_path")
    op.drop_column("documents", "document_kind")

    op.drop_index("ix_sources_external_object_id", "sources")
    op.drop_constraint("fk_sources_external_object_id", "sources", type_="foreignkey")
    op.drop_column("sources", "external_object_id")

    op.drop_index("ix_external_objects_provider_object_type", "external_objects")
    op.drop_index("ix_external_objects_repository_id", "external_objects")
    op.drop_table("external_objects")
    op.drop_index("ix_external_repositories_provider_full_name", "external_repositories")
    op.drop_table("external_repositories")
    op.drop_table("external_connections")
