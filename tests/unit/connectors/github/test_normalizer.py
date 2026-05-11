import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from lore.connector_sdk.models import RawExternalObject
from lore.connectors.github.normalizer import GitHubNormalizer


def _conn_id() -> UUID:
    return uuid4()


def _raw(
    path: str,
    content: str = "content",
    object_type: str = "github.file",
    commit_sha: str = "deadbeef",
) -> RawExternalObject:
    payload = {"path": path, "size": len(content)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return RawExternalObject(
        provider="github",
        object_type=object_type,
        external_id=f"owner/repo:file:{path}"
        if object_type == "github.file"
        else "owner/repo:repository",
        external_url=f"https://github.com/owner/repo/blob/{commit_sha}/{path}",
        connection_id=_conn_id(),
        repository_id=uuid4(),
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={
            "commit_sha": commit_sha,
            "path": path,
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
            "size": len(content),
        },
    )


def test_readme_becomes_documentation_readme() -> None:
    raw = _raw("README.md")
    drafts = GitHubNormalizer().normalize(raw)
    assert len(drafts) == 1
    assert drafts[0].document_kind == "documentation.readme"


def test_docs_markdown_becomes_documentation_markdown() -> None:
    raw = _raw("docs/architecture.md")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "documentation.markdown"


def test_python_file_becomes_code_file() -> None:
    raw = _raw("lore/ingestion/service.py")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "code.file"


def test_test_file_becomes_code_test() -> None:
    raw = _raw("tests/unit/test_foo.py")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "code.test"


def test_pyproject_becomes_config_build() -> None:
    raw = _raw("pyproject.toml")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "config.build"


def test_dockerfile_becomes_config_runtime() -> None:
    raw = _raw("Dockerfile")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "config.runtime"


def test_github_workflow_becomes_config_ci() -> None:
    raw = _raw(".github/workflows/ci.yml")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].document_kind == "config.ci"


def test_version_ref_is_commit_sha() -> None:
    raw = _raw("lore/service.py", commit_sha="deadbeef")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].version_ref == "deadbeef"


def test_logical_path_is_file_path() -> None:
    raw = _raw("lore/ingestion/service.py")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].logical_path == "lore/ingestion/service.py"


def test_content_hash_matches_raw_content_hash() -> None:
    content = "# Hello World"
    raw = _raw("README.md", content=content)
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts[0].content_hash == raw.content_hash


def test_provenance_snapshot_in_metadata() -> None:
    raw = _raw("lore/service.py", commit_sha="abc123")
    drafts = GitHubNormalizer().normalize(raw)
    meta = drafts[0].metadata
    assert meta["commit_sha"] == "abc123"
    assert meta["path"] == "lore/service.py"


def test_repository_object_returns_empty_list() -> None:
    raw = _raw("", object_type="github.repository")
    drafts = GitHubNormalizer().normalize(raw)
    assert drafts == []
