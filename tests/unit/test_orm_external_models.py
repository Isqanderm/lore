from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_object import ExternalObjectORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM


def test_external_connection_table_name() -> None:
    assert ExternalConnectionORM.__tablename__ == "external_connections"


def test_external_repository_table_name() -> None:
    assert ExternalRepositoryORM.__tablename__ == "external_repositories"


def test_external_object_table_name() -> None:
    assert ExternalObjectORM.__tablename__ == "external_objects"


def test_external_object_unique_constraint() -> None:
    table = ExternalObjectORM.__table__
    constraint_names = {c.name for c in table.constraints}  # type: ignore[attr-defined]
    assert "uq_external_objects_connection_provider_id" in constraint_names


def test_external_object_has_required_columns() -> None:
    table = ExternalObjectORM.__table__
    cols = {c.name for c in table.columns}
    assert {
        "provider",
        "object_type",
        "external_id",
        "raw_payload_json",
        "raw_payload_hash",
        "content_hash",
        "fetched_at",
    }.issubset(cols)
