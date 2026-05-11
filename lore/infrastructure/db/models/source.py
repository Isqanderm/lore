from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class SourceORM(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type_raw: Mapped[str] = mapped_column(nullable=False)
    source_type_canonical: Mapped[str] = mapped_column(nullable=False, index=True)
    origin: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    external_object_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_objects.id"), nullable=True, index=True
    )
