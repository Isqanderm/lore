from __future__ import annotations

from datetime import datetime  # noqa: TC003, TCH003
from typing import Any
from uuid import UUID, uuid4  # noqa: TC003, TCH003

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class RepositoryArtifactORM(Base):
    __tablename__ = "repository_artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_repositories.id", name="fk_repository_artifacts_repository_id"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("repository_sync_runs.id", name="fk_repository_artifacts_source_sync_run_id"),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "artifact_type", name="uq_repository_artifact_type"),
        CheckConstraint(
            "artifact_type IN ('repository_brief', 'repository_structure')",
            name="ck_repository_artifact_type",
        ),
        sa.Index("ix_repository_artifacts_repository_id", "repository_id"),
        sa.Index("ix_repository_artifacts_artifact_type", "artifact_type"),
        sa.Index("ix_repository_artifacts_source_sync_run_id", "source_sync_run_id"),
    )
