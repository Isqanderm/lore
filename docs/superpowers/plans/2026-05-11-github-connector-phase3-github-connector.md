# GitHub Connector Foundation — Phase 3: GitHub Connector

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `lore/connectors/github/` — the GitHub-specific connector. No DB access. No imports of ORM or repositories.

**Architecture:** GitHub connector depends only on `lore.connector_sdk` and `lore.schema`. It fetches, hashes, and returns `RawExternalObject` records. Normalization maps raw GitHub objects to `CanonicalDocumentDraft`.

**Tech Stack:** httpx (async HTTP), respx (test mocking), fnmatch for file patterns

**Prerequisites:** Phase 1 (Connector SDK) complete.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Create | `lore/connectors/__init__.py` | package root |
| Create | `lore/connectors/github/__init__.py` | package root |
| Create | `lore/connectors/github/models.py` | GitHubRepoRef, GitHubTreeEntry, GitHubRepositoryTree; parse_github_url |
| Create | `lore/connectors/github/auth.py` | GitHubAuth.from_settings |
| Create | `lore/connectors/github/client.py` | GitHubClient — httpx async, error mapping |
| Create | `lore/connectors/github/file_policy.py` | FileSelectionPolicy |
| Create | `lore/connectors/github/normalizer.py` | GitHubNormalizer |
| Create | `lore/connectors/github/manifest.py` | GITHUB_MANIFEST constant |
| Create | `lore/connectors/github/webhook.py` | skeleton raising UnsupportedCapabilityError |
| Create | `lore/connectors/github/connector.py` | GitHubConnector |
| Create | `tests/unit/connectors/__init__.py` | test package |
| Create | `tests/unit/connectors/github/__init__.py` | test package |
| Create | `tests/unit/connectors/github/test_url_parser.py` | URL parsing tests |
| Create | `tests/unit/connectors/github/test_file_policy.py` | FileSelectionPolicy tests |
| Create | `tests/unit/connectors/github/test_raw_object_hashing.py` | hash determinism tests |
| Create | `tests/unit/connectors/github/test_normalizer.py` | normalizer mapping tests |

---

## Task 8: models.py, auth.py + URL parser tests

**Files:**
- Create: `lore/connectors/__init__.py`
- Create: `lore/connectors/github/__init__.py`
- Create: `lore/connectors/github/models.py`
- Create: `lore/connectors/github/auth.py`
- Create: `tests/unit/connectors/__init__.py`
- Create: `tests/unit/connectors/github/__init__.py`
- Create: `tests/unit/connectors/github/test_url_parser.py`

- [ ] **Step 1: Write URL parser tests**

```python
# tests/unit/connectors/github/test_url_parser.py
import pytest
from lore.connectors.github.models import parse_github_url


def test_parse_https_url() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_https_url_with_trailing_slash() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore/")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_https_url_with_git_suffix() -> None:
    owner, repo = parse_github_url("https://github.com/Isqanderm/lore.git")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_ssh_url() -> None:
    owner, repo = parse_github_url("git@github.com:Isqanderm/lore.git")
    assert owner == "Isqanderm"
    assert repo == "lore"


def test_parse_invalid_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_missing_repo_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm")


def test_parse_blob_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm/lore/blob/main/README.md")


def test_parse_tree_url_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse GitHub URL"):
        parse_github_url("https://github.com/Isqanderm/lore/tree/main")
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/connectors/github/test_url_parser.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create package init files**

```python
# lore/connectors/__init__.py
# (empty)
```

```python
# lore/connectors/github/__init__.py
# (empty)
```

```python
# tests/unit/connectors/__init__.py
# (empty)
```

```python
# tests/unit/connectors/github/__init__.py
# (empty)
```

- [ ] **Step 4: Implement models.py**

```python
# lore/connectors/github/models.py
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class GitHubTreeEntry:
    path: str
    mode: str
    type: str   # "blob" | "tree"
    sha: str
    size: int | None  # None for trees


@dataclass(frozen=True)
class GitHubRepositoryTree:
    branch: str
    commit_sha: str   # head commit SHA — single source of truth for provenance
    tree_sha: str
    entries: list[GitHubTreeEntry]


_HTTPS_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
_SSH_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"
)


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub HTTPS or SSH URL.

    MVP: repository root URLs only. Blob/tree URLs (e.g. /blob/main/README.md,
    /tree/main) are not supported — raise ValueError with a clear message.
    """
    for pattern in (_HTTPS_RE, _SSH_RE):
        m = pattern.match(url.strip())
        if m:
            return m.group("owner"), m.group("repo")
    raise ValueError(
        f"Cannot parse GitHub URL: {url!r}. "
        "Provide a repository root URL (e.g. https://github.com/owner/repo). "
        "Blob/tree/commit URLs are not supported in this version."
    )
```

- [ ] **Step 5: Implement auth.py**

```python
# lore/connectors/github/auth.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lore.connector_sdk.errors import ConnectorConfigurationError

if TYPE_CHECKING:
    from lore.infrastructure.config import Settings


@dataclass(frozen=True)
class GitHubAuth:
    token: str
    auth_mode: str = "env_pat"

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubAuth:
        if not settings.github_token:
            raise ConnectorConfigurationError(
                "GITHUB_TOKEN is not set. Set the GITHUB_TOKEN environment variable."
            )
        return cls(token=settings.github_token.get_secret_value())
```

- [ ] **Step 6: Run URL parser tests**

```
pytest tests/unit/connectors/github/test_url_parser.py -v
```
Expected: 8 PASSED

- [ ] **Step 7: Commit**

```bash
git add \
  lore/connectors/__init__.py \
  lore/connectors/github/__init__.py \
  lore/connectors/github/models.py \
  lore/connectors/github/auth.py \
  tests/unit/connectors/__init__.py \
  tests/unit/connectors/github/__init__.py \
  tests/unit/connectors/github/test_url_parser.py
git commit -m "feat(github): models (parse_github_url, GitHubRepositoryTree) and GitHubAuth"
```

---

## Task 9: file_policy.py + tests

**Files:**
- Create: `lore/connectors/github/file_policy.py`
- Create: `tests/unit/connectors/github/test_file_policy.py`

- [ ] **Step 1: Write file policy tests**

```python
# tests/unit/connectors/github/test_file_policy.py
import pytest
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.models import GitHubTreeEntry


def _entry(path: str, size: int = 1000, type: str = "blob") -> GitHubTreeEntry:
    return GitHubTreeEntry(path=path, mode="100644", type=type, sha="abc", size=size)


def test_readme_included() -> None:
    policy = FileSelectionPolicy()
    assert policy.should_include(_entry("README.md"))
    assert policy.should_include(_entry("README.rst"))


def test_docs_markdown_included() -> None:
    policy = FileSelectionPolicy()
    assert policy.should_include(_entry("docs/architecture.md"))
    assert policy.should_include(_entry("docs/api/spec.md"))


def test_python_file_included() -> None:
    policy = FileSelectionPolicy()
    assert policy.should_include(_entry("lore/ingestion/service.py"))
    assert policy.should_include(_entry("src/core/utils.py"))
    assert policy.should_include(_entry("tests/unit/test_foo.py"))


def test_github_workflow_included() -> None:
    policy = FileSelectionPolicy()
    assert policy.should_include(_entry(".github/workflows/ci.yml"))


def test_pyproject_included() -> None:
    policy = FileSelectionPolicy()
    assert policy.should_include(_entry("pyproject.toml"))
    assert policy.should_include(_entry("package.json"))
    assert policy.should_include(_entry("Dockerfile"))
    assert policy.should_include(_entry("docker-compose.yml"))


def test_node_modules_excluded() -> None:
    policy = FileSelectionPolicy()
    assert not policy.should_include(_entry("node_modules/lodash/index.js"))


def test_dist_excluded() -> None:
    policy = FileSelectionPolicy()
    assert not policy.should_include(_entry("dist/bundle.js"))
    assert not policy.should_include(_entry("build/output.js"))


def test_tree_entries_excluded() -> None:
    policy = FileSelectionPolicy()
    assert not policy.should_include(_entry("src", type="tree"))


def test_oversized_file_excluded() -> None:
    policy = FileSelectionPolicy()
    assert not policy.should_include(_entry("big.py", size=600_000))


def test_filter_returns_only_included() -> None:
    policy = FileSelectionPolicy()
    entries = [
        _entry("README.md"),
        _entry("node_modules/dep.js"),
        _entry("lore/service.py"),
    ]
    result = policy.filter(entries)
    paths = {e.path for e in result}
    assert paths == {"README.md", "lore/service.py"}


def test_custom_max_size() -> None:
    policy = FileSelectionPolicy(max_file_size_bytes=100)
    assert not policy.should_include(_entry("lore/service.py", size=200))
    assert policy.should_include(_entry("lore/service.py", size=50))
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/connectors/github/test_file_policy.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement file_policy.py**

```python
# lore/connectors/github/file_policy.py
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from lore.connectors.github.models import GitHubTreeEntry

_DEFAULT_INCLUDES = [
    "README*",
    "*.md",
    "docs/**",
    "docs/**/*.md",
    "pyproject.toml",
    "package.json",
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows/**",
    ".github/workflows/**/*.yml",
    "src/**",
    "app/**",
    "lib/**",
    "packages/**",
    "tests/**",
    "lore/**",
]

_DEFAULT_EXCLUDES = [
    "node_modules/**",
    "dist/**",
    "build/**",
    ".git/**",
    "vendor/**",
    "coverage/**",
    "*.min.js",
    "*.min.css",
    "*.pyc",
    "__pycache__/**",
]


@dataclass
class FileSelectionPolicy:
    max_file_size_bytes: int = 500_000
    include_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_INCLUDES))
    exclude_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_EXCLUDES))

    def should_include(self, entry: GitHubTreeEntry) -> bool:
        if entry.type != "blob":
            return False
        if entry.size is not None and entry.size > self.max_file_size_bytes:
            return False
        path = entry.path
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(path, pattern):
                return False
        for pattern in self.include_patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    def filter(self, entries: list[GitHubTreeEntry]) -> list[GitHubTreeEntry]:
        return [e for e in entries if self.should_include(e)]
```

- [ ] **Step 4: Run file policy tests**

```
pytest tests/unit/connectors/github/test_file_policy.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add lore/connectors/github/file_policy.py tests/unit/connectors/github/test_file_policy.py
git commit -m "feat(github): FileSelectionPolicy with configurable include/exclude patterns"
```

---

## Task 10: client.py

**Files:**
- Create: `lore/connectors/github/client.py`

Note: client unit tests require respx mocking — written in Phase 3 Task 14 (integration). We do a manual smoke check here.

- [ ] **Step 1: Add httpx to pyproject.toml main deps and respx to dev deps**

In `pyproject.toml`, add to `dependencies`:
```
"httpx>=0.27.0",
```

Add to `[dependency-groups] dev`:
```
"respx>=0.21.0",
```

Install:
```bash
pip install httpx respx
```

- [ ] **Step 2: Implement client.py**

```python
# lore/connectors/github/client.py
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import httpx

from lore.connector_sdk.errors import (
    ConnectorAuthenticationError,
    ConnectorRateLimitError,
    ConnectorError,
    ExternalResourceNotFoundError,
)
from lore.connectors.github.models import GitHubRepositoryTree, GitHubTreeEntry

if TYPE_CHECKING:
    from lore.connectors.github.auth import GitHubAuth
    from lore.infrastructure.config import Settings


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, auth: GitHubAuth) -> None:
        self._auth = auth
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {auth.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubClient:
        from lore.connectors.github.auth import GitHubAuth
        return cls(GitHubAuth.from_settings(settings))

    async def close(self) -> None:
        await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise ConnectorAuthenticationError(
                f"GitHub authentication failed: HTTP {response.status_code}"
            )
        if response.status_code == 404:
            raise ExternalResourceNotFoundError(
                f"GitHub resource not found: {response.url}"
            )
        if response.status_code == 429:
            raise ConnectorRateLimitError("GitHub API rate limit exceeded")
        if response.status_code >= 500:
            raise ConnectorError(
                f"GitHub API server error: HTTP {response.status_code}"
            )
        response.raise_for_status()

    async def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        response = await self._client.get(f"/repos/{owner}/{repo}")
        self._raise_for_status(response)
        return response.json()  # type: ignore[no-any-return]

    async def get_repository_tree(
        self, owner: str, repo: str, branch: str
    ) -> GitHubRepositoryTree:
        """Atomically resolve branch → commit SHA → tree entries.

        Single operation prevents race between branch pointer and file content.
        Returns commit_sha as the provenance anchor for all objects in this sync.
        """
        # 1. Resolve branch → commit SHA
        ref_response = await self._client.get(f"/repos/{owner}/{repo}/git/refs/heads/{branch}")
        self._raise_for_status(ref_response)
        ref_data = ref_response.json()
        commit_sha: str = ref_data["object"]["sha"]

        # 2. Resolve commit SHA → tree SHA
        commit_response = await self._client.get(
            f"/repos/{owner}/{repo}/git/commits/{commit_sha}"
        )
        self._raise_for_status(commit_response)
        commit_data = commit_response.json()
        tree_sha: str = commit_data["tree"]["sha"]

        # 3. Fetch recursive tree
        tree_response = await self._client.get(
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        self._raise_for_status(tree_response)
        tree_data = tree_response.json()

        entries = [
            GitHubTreeEntry(
                path=item["path"],
                mode=item["mode"],
                type=item["type"],
                sha=item["sha"],
                size=item.get("size"),
            )
            for item in tree_data.get("tree", [])
        ]

        return GitHubRepositoryTree(
            branch=branch,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            entries=entries,
        )

    async def get_file_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> str:
        """Fetch file content decoded from base64. Raises ConnectorError for binary files."""
        response = await self._client.get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        self._raise_for_status(response)
        data = response.json()
        encoded = data.get("content", "")
        raw_bytes = base64.b64decode(encoded.replace("\n", ""))
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConnectorError(
                f"File {path} in {owner}/{repo} is not valid UTF-8 (binary?)"
            ) from exc
```

- [ ] **Step 3: Run unit tests to confirm no regressions**

```
pytest tests/unit/ -v
```
Expected: all PASSED (no new tests for client yet — integration tests cover it via respx)

- [ ] **Step 4: Commit**

```bash
git add lore/connectors/github/client.py pyproject.toml
git commit -m "feat(github): GitHubClient with atomic get_repository_tree and error mapping"
```

---

## Task 11: normalizer.py + tests

**Files:**
- Create: `lore/connectors/github/normalizer.py`
- Create: `tests/unit/connectors/github/test_raw_object_hashing.py`
- Create: `tests/unit/connectors/github/test_normalizer.py`

- [ ] **Step 1: Write hashing and normalizer tests**

```python
# tests/unit/connectors/github/test_raw_object_hashing.py
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from lore.connector_sdk.models import RawExternalObject


def _make_raw(
    path: str = "README.md",
    content: str = "# Hello",
    payload: dict | None = None,
) -> RawExternalObject:
    if payload is None:
        payload = {"path": path, "size": len(content)}
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    raw_payload_hash = "sha256:" + hashlib.sha256(canonical_json.encode()).hexdigest()
    content_hash = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    conn_id = uuid4()
    return RawExternalObject(
        provider="github",
        object_type="github.file",
        external_id=f"owner/repo:file:{path}",
        external_url=f"https://github.com/owner/repo/blob/abc123/{path}",
        connection_id=conn_id,
        repository_id=uuid4(),
        raw_payload=payload,
        raw_payload_hash=raw_payload_hash,
        content=content,
        content_hash=content_hash,
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": "abc123", "path": path, "owner": "owner", "repo": "repo"},
    )


def test_external_id_stable_by_path() -> None:
    raw = _make_raw(path="lore/service.py")
    assert raw.external_id == "owner/repo:file:lore/service.py"
    # Path-based, not blob-SHA-based:
    assert "abc123" not in raw.external_id


def test_raw_payload_hash_deterministic() -> None:
    payload = {"path": "README.md", "size": 42}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    raw = _make_raw(payload=payload)
    assert raw.raw_payload_hash == expected


def test_content_hash_deterministic() -> None:
    raw = _make_raw(content="# Hello World")
    expected = "sha256:" + hashlib.sha256("# Hello World".encode()).hexdigest()
    assert raw.content_hash == expected


def test_commit_sha_in_metadata() -> None:
    raw = _make_raw()
    assert "commit_sha" in raw.metadata
    assert raw.metadata["commit_sha"] == "abc123"
```

```python
# tests/unit/connectors/github/test_normalizer.py
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from lore.connector_sdk.models import CanonicalDocumentDraft, RawExternalObject
from lore.connectors.github.normalizer import GitHubNormalizer


def _conn_id():
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
        external_id=f"owner/repo:file:{path}" if object_type == "github.file" else "owner/repo:repository",
        external_url=f"https://github.com/owner/repo/blob/{commit_sha}/{path}",
        connection_id=_conn_id(),
        repository_id=uuid4(),
        raw_payload=payload,
        raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        content=content,
        content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        source_updated_at=None,
        fetched_at=datetime.now(UTC),
        metadata={"commit_sha": commit_sha, "path": path, "owner": "owner", "repo": "repo", "branch": "main", "size": len(content)},
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/unit/connectors/github/test_normalizer.py tests/unit/connectors/github/test_raw_object_hashing.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement normalizer.py**

```python
# lore/connectors/github/normalizer.py
from __future__ import annotations

import fnmatch
from typing import Any

from lore.connector_sdk.models import CanonicalDocumentDraft, ProvenanceDraft, RawExternalObject


def _classify_file(path: str) -> str:
    """Map file path to document_kind."""
    name = path.split("/")[-1]

    if fnmatch.fnmatch(name, "README*"):
        return "documentation.readme"

    if fnmatch.fnmatch(path, "tests/**/*.py") or fnmatch.fnmatch(name, "test_*.py") or fnmatch.fnmatch(name, "*_test.py"):
        return "code.test"

    if fnmatch.fnmatch(path, ".github/workflows/**"):
        return "config.ci"

    if name in ("pyproject.toml", "package.json", "setup.cfg", "setup.py"):
        return "config.build"

    if name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
        return "config.runtime"

    if path.endswith(".md") or path.endswith(".rst"):
        return "documentation.markdown"

    if path.endswith(".py"):
        return "code.file"

    return "code.file"


class GitHubNormalizer:
    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        if raw.object_type == "github.file":
            return [self._normalize_file(raw)]
        # github.repository → future: repository_brief artifact. Skip for now.
        return []

    def _normalize_file(self, raw: RawExternalObject) -> CanonicalDocumentDraft:
        path: str = raw.metadata.get("path", raw.external_id)
        commit_sha: str = raw.metadata["commit_sha"]  # mandatory for file objects
        document_kind = _classify_file(path)
        title = path.split("/")[-1]

        provenance = ProvenanceDraft(
            provider=raw.provider,
            external_id=raw.external_id,
            external_url=raw.external_url,
            connection_id=raw.connection_id,
            repository_id=raw.repository_id,
            raw_payload_hash=raw.raw_payload_hash,
        )

        meta: dict[str, Any] = {
            "commit_sha": commit_sha,
            "path": path,
            "owner": raw.metadata.get("owner"),
            "repo": raw.metadata.get("repo"),
            "branch": raw.metadata.get("branch"),
        }

        return CanonicalDocumentDraft(
            document_kind=document_kind,
            logical_path=path,
            title=title,
            content=raw.content or "",
            content_hash=raw.content_hash or "",
            version_ref=commit_sha,
            source_updated_at=raw.source_updated_at,
            provenance=provenance,
            metadata=meta,
        )
```

- [ ] **Step 4: Run normalizer tests**

```
pytest tests/unit/connectors/github/test_normalizer.py tests/unit/connectors/github/test_raw_object_hashing.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add lore/connectors/github/normalizer.py tests/unit/connectors/github/test_normalizer.py tests/unit/connectors/github/test_raw_object_hashing.py
git commit -m "feat(github): GitHubNormalizer with document_kind mapping + tests"
```

---

## Task 12: manifest.py, webhook.py, connector.py

**Files:**
- Create: `lore/connectors/github/manifest.py`
- Create: `lore/connectors/github/webhook.py`
- Create: `lore/connectors/github/connector.py`

- [ ] **Step 1: Implement manifest.py**

```python
# lore/connectors/github/manifest.py
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest

GITHUB_CAPABILITIES = ConnectorCapabilities(
    supports_full_sync=True,
    supports_incremental_sync=False,
    supports_webhooks=False,
    supports_repository_tree=True,
    supports_files=True,
    supports_issues=False,
    supports_pull_requests=False,
    supports_comments=False,
    supports_releases=False,
    supports_permissions=False,
    object_types=("github.repository", "github.file"),
)

GITHUB_MANIFEST = ConnectorManifest(
    connector_id="github",
    display_name="GitHub",
    version="0.1.0",
    capabilities=GITHUB_CAPABILITIES,
)
```

- [ ] **Step 2: Implement webhook.py (skeleton)**

```python
# lore/connectors/github/webhook.py
from lore.connector_sdk.errors import UnsupportedCapabilityError


async def verify_webhook(payload: bytes, headers: dict[str, str]) -> bool:
    raise UnsupportedCapabilityError(
        "GitHub webhooks are not supported in this version. "
        "supports_webhooks=False in ConnectorCapabilities."
    )


async def parse_webhook(payload: bytes, headers: dict[str, str]) -> None:
    raise UnsupportedCapabilityError(
        "GitHub webhooks are not supported in this version."
    )
```

- [ ] **Step 3: Implement connector.py**

```python
# lore/connectors/github/connector.py
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.errors import ConnectorError, UnsupportedCapabilityError
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
    WebhookEvent,
)
from lore.connectors.github.client import GitHubClient
from lore.connectors.github.file_policy import FileSelectionPolicy
from lore.connectors.github.manifest import GITHUB_MANIFEST
from lore.connectors.github.models import GitHubTreeEntry, parse_github_url
from lore.connectors.github.normalizer import GitHubNormalizer


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


class GitHubConnector(BaseConnector):
    def __init__(
        self,
        client: GitHubClient,
        file_policy: FileSelectionPolicy,
        normalizer: GitHubNormalizer,
    ) -> None:
        self._client = client
        self._file_policy = file_policy
        self._normalizer = normalizer

    @property
    def manifest(self) -> ConnectorManifest:
        return GITHUB_MANIFEST

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        owner, repo = parse_github_url(resource_uri)
        meta = await self._client.get_repository(owner, repo)
        return ExternalContainerDraft(
            provider="github",
            owner=owner,
            name=repo,
            full_name=meta["full_name"],
            default_branch=meta["default_branch"],
            html_url=meta["html_url"],
            visibility=meta.get("visibility"),
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        owner, repo = parse_github_url(request.resource_uri)
        repo_meta = await self._client.get_repository(owner, repo)
        branch: str = repo_meta["default_branch"]

        tree = await self._client.get_repository_tree(owner, repo, branch)
        head_sha = tree.commit_sha  # provenance anchor for all objects in this sync

        repo_raw = self._build_repo_raw(repo_meta, request, head_sha)

        selected = self._file_policy.filter(tree.entries)
        file_raws: list[RawExternalObject] = []
        warnings: list[str] = []
        for entry in selected:
            try:
                content = await self._client.get_file_content(owner, repo, entry.path, head_sha)
            except ConnectorError as exc:
                warnings.append(f"Skipped {entry.path}: {exc}")
                continue
            # Unexpected exceptions propagate — do not swallow them silently.
            file_raws.append(
                self._build_file_raw(entry, content, request, owner, repo, branch, head_sha)
            )

        return SyncResult(
            connector_id="github",
            raw_objects=[repo_raw, *file_raws],
            warnings=warnings,
        )

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return self._normalizer.normalize(raw)

    async def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        raise UnsupportedCapabilityError("webhooks")

    async def parse_webhook(self, payload: bytes, headers: dict[str, str]) -> WebhookEvent:
        raise UnsupportedCapabilityError("webhooks")

    def _build_repo_raw(
        self,
        repo_meta: dict,
        request: FullSyncRequest,
        head_sha: str,
    ) -> RawExternalObject:
        owner = repo_meta["owner"]["login"]
        repo = repo_meta["name"]
        payload = {
            "full_name": repo_meta["full_name"],
            "default_branch": repo_meta["default_branch"],
            "description": repo_meta.get("description"),
            "html_url": repo_meta["html_url"],
            "visibility": repo_meta.get("visibility"),
        }
        return RawExternalObject(
            provider="github",
            object_type="github.repository",
            external_id=f"{owner}/{repo}:repository",
            external_url=repo_meta["html_url"],
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash=_canonical_hash(payload),
            content=None,
            content_hash=None,
            source_updated_at=None,
            fetched_at=datetime.now(UTC),
            metadata={"commit_sha": head_sha, "owner": owner, "repo": repo},
        )

    def _build_file_raw(
        self,
        entry: GitHubTreeEntry,
        content: str,
        request: FullSyncRequest,
        owner: str,
        repo: str,
        branch: str,
        head_sha: str,
    ) -> RawExternalObject:
        payload = {
            "path": entry.path,
            "sha": entry.sha,
            "size": entry.size,
            "mode": entry.mode,
        }
        return RawExternalObject(
            provider="github",
            object_type="github.file",
            external_id=f"{owner}/{repo}:file:{entry.path}",
            external_url=f"https://github.com/{owner}/{repo}/blob/{head_sha}/{entry.path}",
            connection_id=request.connection_id,
            repository_id=request.repository_id,
            raw_payload=payload,
            raw_payload_hash=_canonical_hash(payload),
            content=content,
            content_hash=_content_hash(content),
            source_updated_at=None,  # no per-file commit history API calls
            fetched_at=datetime.now(UTC),
            metadata={
                "commit_sha": head_sha,
                "path": entry.path,
                "owner": owner,
                "repo": repo,
                "branch": branch,
                "size": entry.size,
            },
        )
```

- [ ] **Step 4: Run all unit tests including import boundary**

```
pytest tests/unit/ -v
```
Expected: all PASSED

The import boundary test must still pass — `lore.ingestion` does not import `lore.connectors.github`.

- [ ] **Step 5: Commit**

```bash
git add \
  lore/connectors/github/manifest.py \
  lore/connectors/github/webhook.py \
  lore/connectors/github/connector.py
git commit -m "feat(github): GitHubConnector — full_sync, inspect_resource, normalize"
```

---

## Phase 3 complete

GitHub Connector is fully implemented. Import boundary invariant verified. Proceed to Phase 4: Ingestion Service.

Next plan file: `2026-05-11-github-connector-phase4-ingestion.md`
