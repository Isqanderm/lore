from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):  # noqa: UP046
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
