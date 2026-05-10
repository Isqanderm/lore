from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SourceType(str, Enum):
    GIT_REPO = "git_repo"
    MARKDOWN = "markdown"
    ADR = "adr"
    SLACK = "slack"
    CONFLUENCE = "confluence"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Source:
    id: UUID
    source_type_raw: str
    source_type_canonical: SourceType
    origin: str
    created_at: datetime
    updated_at: datetime
