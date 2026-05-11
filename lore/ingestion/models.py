from dataclasses import dataclass, field


@dataclass
class IngestionReport:
    raw_objects_processed: int = 0
    documents_created: int = 0
    versions_created: int = 0
    versions_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
