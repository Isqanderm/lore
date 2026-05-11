from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalObjectORM(Base):
    __tablename__ = "external_objects"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider",
            "external_id",
            name="uq_external_objects_connection_provider_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    repository_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_repositories.id"), nullable=True, index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_connections.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(nullable=False)
    object_type: Mapped[str] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(nullable=False)
    external_url: Mapped[str | None] = mapped_column(nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    raw_payload_hash: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(nullable=True)
    content_hash: Mapped[str | None] = mapped_column(nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
