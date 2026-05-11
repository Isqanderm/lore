from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class ExternalConnectionORM(Base):
    __tablename__ = "external_connections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(nullable=False)
    auth_mode: Mapped[str] = mapped_column(nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(nullable=True)
    installation_id: Mapped[str | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
