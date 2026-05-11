from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from lore.ingestion.models import IngestionReport
from lore.schema.document import Document, DocumentVersion
from lore.schema.source import Source, SourceType

if TYPE_CHECKING:
    from lore.connector_sdk.base import BaseConnector
    from lore.connector_sdk.models import CanonicalDocumentDraft, RawExternalObject, SyncResult


def _canonical_source_type(provider: str) -> SourceType:
    if provider in {"github", "gitlab"}:
        return SourceType.GIT_REPO
    if provider == "confluence":
        return SourceType.CONFLUENCE
    return SourceType.UNKNOWN


class IngestionService:
    def __init__(
        self,
        external_object_repo: Any,
        source_repo: Any,
        document_repo: Any,
        document_version_repo: Any,
    ) -> None:
        self._ext_obj_repo = external_object_repo
        self._source_repo = source_repo
        self._doc_repo = document_repo
        self._dv_repo = document_version_repo

    async def ingest_sync_result(
        self,
        sync_result: SyncResult,
        connector: BaseConnector,
    ) -> IngestionReport:
        report = IngestionReport(warnings=list(sync_result.warnings))
        for raw in sync_result.raw_objects:
            report.raw_objects_processed += 1
            persisted = await self._upsert_raw_object(raw)
            drafts = connector.normalize(raw)
            for draft in drafts:
                created_doc, created_version = await self._upsert_document(
                    draft, raw, external_object_id=persisted.id
                )
                if created_doc:
                    report.documents_created += 1
                if created_version:
                    report.versions_created += 1
                else:
                    report.versions_skipped += 1
        return report

    async def _upsert_raw_object(self, raw: RawExternalObject) -> Any:
        return await self._ext_obj_repo.upsert(raw)

    async def _upsert_document(
        self,
        draft: CanonicalDocumentDraft,
        raw: RawExternalObject,
        external_object_id: UUID,
    ) -> tuple[bool, bool]:
        """Return (document_created, version_created)."""
        # 1. Find or create source
        source = await self._source_repo.get_by_external_object_id(external_object_id)
        if source is None:
            now = datetime.now(UTC)
            source = await self._source_repo.create_with_external_object(
                Source(
                    id=uuid4(),
                    source_type_raw=raw.provider,
                    source_type_canonical=_canonical_source_type(raw.provider),
                    origin=draft.provenance.external_url or draft.provenance.external_id,
                    created_at=now,
                    updated_at=now,
                ),
                external_object_id=external_object_id,
            )

        # 2. Find or create document
        doc_created = False
        doc = await self._doc_repo.get_by_source_kind_path(
            source.id,
            draft.document_kind,
            draft.logical_path,  # pass None as-is — repository handles IS NULL correctly
        )
        if doc is None:
            now = datetime.now(UTC)
            doc = await self._doc_repo.create(
                Document(
                    id=uuid4(),
                    source_id=source.id,
                    title=draft.title,
                    path=draft.logical_path or draft.provenance.external_id,
                    document_kind=draft.document_kind,
                    logical_path=draft.logical_path,
                    metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
            doc_created = True

        # 3. Check idempotency via checksum
        latest = await self._dv_repo.get_latest_version(doc.id)
        if latest is not None and latest.checksum == draft.content_hash:
            return doc_created, False  # same content — skip

        # 4. Create new version with provenance snapshot in metadata
        max_version = await self._dv_repo.get_max_version(doc.id)
        provenance_snapshot: dict[str, Any] = {
            "external_id": raw.external_id,
            "external_url": raw.external_url,
            "raw_payload_hash": raw.raw_payload_hash,
            "commit_sha": raw.metadata.get("commit_sha"),
            "path": raw.metadata.get("path"),
        }
        await self._dv_repo.create(
            DocumentVersion(
                id=uuid4(),
                document_id=doc.id,
                version=max_version + 1,
                content=draft.content,
                checksum=draft.content_hash,
                version_ref=draft.version_ref,
                source_updated_at=draft.source_updated_at,
                metadata=provenance_snapshot,
                created_at=datetime.now(UTC),
            )
        )
        return doc_created, True
