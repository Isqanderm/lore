from __future__ import annotations

from datetime import datetime  # noqa: TC003, TCH003
from typing import Any
from uuid import UUID, uuid4  # noqa: TC003, TCH003

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ChunkORM(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    embedding_ref: Mapped[str | None] = mapped_column(
        nullable=True,
        comment="Format: provider:model:version:sha256hash",
    )
    text_search: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    __table_args__ = (
        # HNSW index requires pgvector 0.8.0+ with 3072-dim support. Add separately once DB is running.
        Index("ix_chunks_text_search", "text_search", postgresql_using="gin"),
    )
