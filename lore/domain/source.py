from lore.schema.source import SourceType

_CANONICAL_MAP: dict[str, SourceType] = {
    "git_repo": SourceType.GIT_REPO,
    "git": SourceType.GIT_REPO,
    "github": SourceType.GIT_REPO,
    "gitlab": SourceType.GIT_REPO,
    "bitbucket": SourceType.GIT_REPO,
    "markdown": SourceType.MARKDOWN,
    "md": SourceType.MARKDOWN,
    "adr": SourceType.ADR,
    "architectural_decision": SourceType.ADR,
    "architectural_decision_record": SourceType.ADR,
    "slack": SourceType.SLACK,
    "confluence": SourceType.CONFLUENCE,
    "wiki": SourceType.CONFLUENCE,
}


def normalize_source_type(raw: str) -> SourceType:
    return _CANONICAL_MAP.get(raw.strip().lower(), SourceType.UNKNOWN)
