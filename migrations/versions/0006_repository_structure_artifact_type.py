"""repository_structure — expand artifact_type check constraint

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief', 'repository_structure')",
    )


def downgrade() -> None:
    # Delete repository_structure rows first — otherwise restoring the old constraint
    # (which only allows 'repository_brief') will fail due to existing rows.
    op.execute("DELETE FROM repository_artifacts WHERE artifact_type = 'repository_structure'")
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief')",
    )
