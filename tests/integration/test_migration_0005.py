"""Schema tests for migration 0005 — document active state columns."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _column_exists(engine: AsyncEngine, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        scalar_result = result.scalar()
        return scalar_result is not None


async def _column_nullable(engine: AsyncEngine, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        scalar_result = result.scalar()
        return scalar_result == "YES"


async def _column_default(engine: AsyncEngine, table: str, column: str) -> str | None:
    async with engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
        scalar_result = result.scalar()
        return str(scalar_result) if scalar_result is not None else None


async def test_m_is_active_column_exists(db_engine: AsyncEngine) -> None:
    assert await _column_exists(db_engine, "documents", "is_active")


async def test_m_is_active_not_nullable(db_engine: AsyncEngine) -> None:
    assert not await _column_nullable(db_engine, "documents", "is_active")


async def test_m_is_active_default_true(db_engine: AsyncEngine) -> None:
    default = await _column_default(db_engine, "documents", "is_active")
    assert default is not None
    assert "true" in default.lower()


async def test_m_deleted_at_column_exists_and_nullable(db_engine: AsyncEngine) -> None:
    assert await _column_exists(db_engine, "documents", "deleted_at")
    assert await _column_nullable(db_engine, "documents", "deleted_at")


async def test_m_first_seen_sync_run_id_exists_and_nullable(
    db_engine: AsyncEngine,
) -> None:
    assert await _column_exists(db_engine, "documents", "first_seen_sync_run_id")
    assert await _column_nullable(db_engine, "documents", "first_seen_sync_run_id")


async def test_m_last_seen_sync_run_id_exists_and_nullable(
    db_engine: AsyncEngine,
) -> None:
    assert await _column_exists(db_engine, "documents", "last_seen_sync_run_id")
    assert await _column_nullable(db_engine, "documents", "last_seen_sync_run_id")
