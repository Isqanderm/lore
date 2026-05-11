from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from lore.infrastructure.db.base import Base


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(nullable=False)
    path: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentVersionORM(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
