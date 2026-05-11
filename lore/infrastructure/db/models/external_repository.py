from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalRepositoryORM(Base):
    __tablename__ = "external_repositories"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_connections.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(nullable=False)
    owner: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(nullable=False)
    default_branch: Mapped[str] = mapped_column(nullable=False)
    html_url: Mapped[str] = mapped_column(nullable=False)
    visibility: Mapped[str | None] = mapped_column(nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
