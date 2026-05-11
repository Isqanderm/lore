from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

import pytest
import sqlalchemy


@pytest.mark.integration
async def test_external_connections_table_exists(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='external_connections'"
            )
        )
        assert result.scalar() == "external_connections"


@pytest.mark.integration
async def test_external_repositories_table_exists(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='external_repositories'"
            )
        )
        assert result.scalar() == "external_repositories"


@pytest.mark.integration
async def test_external_objects_unique_constraint(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name='external_objects' "
                "AND constraint_type='UNIQUE' "
                "AND constraint_name='uq_external_objects_connection_provider_id'"
            )
        )
        assert result.scalar() is not None


@pytest.mark.integration
async def test_sources_has_external_object_id_column(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='sources' AND column_name='external_object_id'"
            )
        )
        assert result.scalar() == "external_object_id"


@pytest.mark.integration
async def test_document_versions_has_version_ref(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='document_versions' AND column_name='version_ref'"
            )
        )
        assert result.scalar() == "version_ref"
