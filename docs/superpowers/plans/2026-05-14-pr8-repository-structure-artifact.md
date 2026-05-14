# PR #8 — Repository Structure Artifact: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `repository_structure` artifact type that classifies active file paths into tree, manifests, entrypoints, infrastructure, and roots — with the same generate/get/fresh/stale lifecycle as `repository_brief`.

**Architecture:** Copy the `RepositoryBriefService` pattern into `RepositoryStructureService` without abstraction. Pure path-classification functions live in `repository_structure_models.py` and are tested independently. Migration 0006 expands the DB check constraint to allow the new artifact type. Two new API endpoints live in the existing `repository_artifacts.py` router.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest-asyncio, testcontainers.

---

## File Map

| File | Action |
|---|---|
| `lore/schema/repository_artifact.py` | Add `ARTIFACT_TYPE_REPOSITORY_STRUCTURE` constant |
| `lore/infrastructure/db/models/repository_artifact.py` | Update `CheckConstraint` to allow `repository_structure` |
| `lore/artifacts/repository_structure_models.py` | **New** — frozen dataclasses + 7 pure classification functions |
| `lore/artifacts/repository_structure_service.py` | **New** — `RepositoryStructureService` with `generate_structure` / `get_structure` |
| `migrations/versions/0006_repository_structure_artifact_type.py` | **New** — expand `ck_repository_artifact_type` constraint |
| `apps/api/routes/v1/repository_artifacts.py` | Add structure response models + endpoints + builder |
| `tests/unit/artifacts/test_repository_structure_models.py` | **New** — unit tests for pure functions |
| `tests/unit/artifacts/test_repository_structure_service.py` | **New** — unit tests for service using existing fakes |
| `tests/integration/test_migration_0006.py` | **New** — verifies constraint allows `repository_structure` |
| `tests/integration/test_repository_structure_api.py` | **New** — API lifecycle tests A–F |

`apps/api/main.py` — **do not modify**. `tests/unit/artifacts/_fakes.py` — modify only if a new method is needed.

> **Why the ORM model must also be updated:** Integration tests use `Base.metadata.create_all` to build the test DB schema, bypassing Alembic. If `RepositoryArtifactORM.__table_args__` still has `artifact_type IN ('repository_brief')`, the test DB will reject `repository_structure` inserts even though migration 0006 is correct.

---

## Task 1: Add ARTIFACT_TYPE_REPOSITORY_STRUCTURE to schema

**Files:**
- Modify: `lore/schema/repository_artifact.py`

- [ ] **Step 1: Add the constant**

Open `lore/schema/repository_artifact.py`. It currently reads:

```python
ARTIFACT_TYPE_REPOSITORY_BRIEF = "repository_brief"
```

Add the new constant directly after:

```python
ARTIFACT_TYPE_REPOSITORY_BRIEF = "repository_brief"
ARTIFACT_TYPE_REPOSITORY_STRUCTURE = "repository_structure"
```

- [ ] **Step 2: Commit**

```bash
git add lore/schema/repository_artifact.py
git commit -m "feat: add ARTIFACT_TYPE_REPOSITORY_STRUCTURE constant"
```

---

## Task 2: Write failing unit tests for pure classification functions

**Files:**
- Create: `tests/unit/artifacts/test_repository_structure_models.py`

These tests will fail to import until Task 3 creates the module — that is the expected TDD failure.

- [ ] **Step 1: Create the test file**

```python
# tests/unit/artifacts/test_repository_structure_models.py
from __future__ import annotations

import pytest

from lore.artifacts.repository_structure_models import (
    EntrypointCandidate,
    ManifestEntry,
    TopLevelDirectoryEntry,
    classify_roots,
    detect_entrypoint_candidates,
    detect_infrastructure,
    detect_manifests,
    get_top_level_directories,
    get_top_level_files,
    normalize_path,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Canonical fixture paths used across tests
# ---------------------------------------------------------------------------

CANONICAL_PATHS = [
    "README.md",
    "pyproject.toml",
    "Dockerfile",
    "lore/ingestion/service.py",
    "lore/sync/service.py",
    "tests/unit/test_service.py",
    "docs/index.md",
    ".github/workflows/ci.yml",
    "apps/api/main.py",
]


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


def test_normalize_path_strips_leading_dot_slash() -> None:
    assert normalize_path("./README.md") == "README.md"


def test_normalize_path_preserves_dot_directories() -> None:
    assert normalize_path(".github/workflows/ci.yml") == ".github/workflows/ci.yml"


def test_normalize_path_strips_whitespace() -> None:
    assert normalize_path("  README.md  ") == "README.md"


# ---------------------------------------------------------------------------
# get_top_level_files / get_top_level_directories
# ---------------------------------------------------------------------------


def test_top_level_files_and_directories() -> None:
    files = get_top_level_files(CANONICAL_PATHS)
    dirs = get_top_level_directories(CANONICAL_PATHS)

    # Top-level files: no "/" in path
    assert "README.md" in files
    assert "pyproject.toml" in files
    assert "Dockerfile" in files
    # Nested paths must not appear in top-level files
    assert "lore/ingestion/service.py" not in files
    assert "apps/api/main.py" not in files

    # Top-level directories: first segment of paths that contain "/"
    dir_paths = [e.path for e in dirs]
    assert ".github" in dir_paths
    assert "apps" in dir_paths
    assert "docs" in dir_paths
    assert "lore" in dir_paths
    assert "tests" in dir_paths

    # File counts
    lore_entry = next(e for e in dirs if e.path == "lore")
    assert lore_entry.files == 2  # service.py x2 under lore/

    # Sorted alphabetically
    assert files == sorted(files)
    assert [e.path for e in dirs] == sorted(e.path for e in dirs)


def test_top_level_files_distinct() -> None:
    paths = ["README.md", "README.md", "setup.py"]
    files = get_top_level_files(paths)
    assert files.count("README.md") == 1


def test_top_level_directories_distinct_counts() -> None:
    paths = ["src/a.py", "src/b.py", "src/c.py"]
    dirs = get_top_level_directories(paths)
    assert len(dirs) == 1
    assert dirs[0].path == "src"
    assert dirs[0].files == 3


# ---------------------------------------------------------------------------
# detect_manifests
# ---------------------------------------------------------------------------


def test_detect_manifests_root_and_nested() -> None:
    paths = [
        "pyproject.toml",
        "README.md",
        "services/api/package.json",
        "apps/web/package.json",
        "go.mod",
    ]
    manifests = detect_manifests(paths)
    manifest_map = {m.path: m.kind for m in manifests}

    assert manifest_map["pyproject.toml"] == "python.project"
    assert manifest_map["services/api/package.json"] == "node.package"
    assert manifest_map["apps/web/package.json"] == "node.package"
    assert manifest_map["go.mod"] == "go.module"
    assert "README.md" not in manifest_map


def test_detect_manifests_all_supported_basenames() -> None:
    paths = [
        "requirements.txt",
        "poetry.lock",
        "Pipfile",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "settings.gradle",
        "build.gradle.kts",
        "Gemfile",
        "composer.json",
    ]
    manifests = detect_manifests(paths)
    assert len(manifests) == len(paths)


def test_detect_manifests_sorted_by_path() -> None:
    paths = ["zzz/package.json", "aaa/package.json"]
    manifests = detect_manifests(paths)
    assert manifests[0].path == "aaa/package.json"
    assert manifests[1].path == "zzz/package.json"


def test_detect_manifests_deduplicates_paths() -> None:
    manifests = detect_manifests(["package.json", "package.json"])
    assert manifests == [ManifestEntry(path="package.json", kind="node.package")]


# ---------------------------------------------------------------------------
# detect_entrypoint_candidates
# ---------------------------------------------------------------------------


def test_detect_entrypoint_candidates_specificity() -> None:
    """apps/api/main.py must resolve to fastapi.app_candidate, NOT python.main."""
    paths = ["apps/api/main.py", "manage.py", "server.ts"]
    candidates = detect_entrypoint_candidates(paths)
    cmap = {c.path: c.kind for c in candidates}

    assert cmap["apps/api/main.py"] == "fastapi.app_candidate"
    assert cmap["manage.py"] == "django.manage"
    assert cmap["server.ts"] == "node.server"


def test_detect_entrypoint_path_ending_api_main() -> None:
    """Any path ending in /api/main.py → fastapi.app_candidate."""
    candidates = detect_entrypoint_candidates(["internal/api/main.py"])
    assert candidates[0].kind == "fastapi.app_candidate"


def test_detect_entrypoint_generic_main_py() -> None:
    """main.py that doesn't match path-specific rules → python.main."""
    candidates = detect_entrypoint_candidates(["cli/main.py"])
    assert candidates[0].kind == "python.main"


def test_detect_entrypoint_go_cmd_pattern() -> None:
    candidates = detect_entrypoint_candidates(["cmd/server/main.go"])
    assert candidates[0].kind == "go.main"


def test_detect_entrypoint_src_index_ts() -> None:
    candidates = detect_entrypoint_candidates(["src/index.ts"])
    assert candidates[0].kind == "node.entry_candidate"


def test_detect_entrypoint_nested_src_main_ts() -> None:
    candidates = detect_entrypoint_candidates(["packages/ui/src/main.ts"])
    assert candidates[0].kind == "node.entry_candidate"


def test_detect_entrypoint_candidates_sorted() -> None:
    paths = ["zzz/server.js", "aaa/app.py"]
    candidates = detect_entrypoint_candidates(paths)
    assert candidates[0].path == "aaa/app.py"


def test_detect_entrypoint_nested_go_cmd_pattern() -> None:
    """Go cmd rule must match nested paths, not only root-level."""
    candidates = detect_entrypoint_candidates(["services/api/cmd/server/main.go"])
    assert len(candidates) == 1
    assert candidates[0].kind == "go.main"


def test_detect_entrypoints_deduplicates_paths() -> None:
    candidates = detect_entrypoint_candidates(["app.py", "app.py"])
    assert candidates == [EntrypointCandidate(path="app.py", kind="python.app")]


# ---------------------------------------------------------------------------
# detect_infrastructure
# ---------------------------------------------------------------------------


def test_detect_infrastructure_files() -> None:
    paths = [
        "Dockerfile",
        "Dockerfile.dev",
        "docker-compose.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yaml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        "apps/api/migrations/0001_init.py",
        "migrations/0002_add_users.py",
    ]
    infra = detect_infrastructure(paths)

    assert "Dockerfile" in infra.docker_files
    assert "Dockerfile.dev" in infra.docker_files
    assert "docker-compose.yml" in infra.docker_files

    assert ".github/workflows/ci.yml" in infra.ci_files
    assert ".github/workflows/deploy.yaml" in infra.ci_files
    assert ".gitlab-ci.yml" in infra.ci_files
    assert ".circleci/config.yml" in infra.ci_files

    assert "migrations" in infra.migration_dirs
    assert "apps/api/migrations" in infra.migration_dirs


def test_detect_infrastructure_ci_uses_path_prefix_not_basename() -> None:
    """Ensure .circleci/ is detected via path prefix, not basename matching."""
    paths = [".circleci/config.yml"]
    infra = detect_infrastructure(paths)
    assert ".circleci/config.yml" in infra.ci_files


def test_detect_infrastructure_alembic_dir() -> None:
    paths = ["alembic/env.py", "alembic/versions/0001.py"]
    infra = detect_infrastructure(paths)
    assert "alembic" in infra.migration_dirs


def test_detect_infrastructure_lists_sorted() -> None:
    paths = ["zzz/Dockerfile", "aaa/docker-compose.yml"]
    infra = detect_infrastructure(paths)
    assert infra.docker_files == sorted(infra.docker_files)


def test_detect_infrastructure_deduplicates_paths() -> None:
    infra = detect_infrastructure(["Dockerfile", "Dockerfile", ".github/workflows/ci.yml", ".github/workflows/ci.yml"])
    assert infra.docker_files == ["Dockerfile"]
    assert infra.ci_files == [".github/workflows/ci.yml"]


# ---------------------------------------------------------------------------
# classify_roots
# ---------------------------------------------------------------------------


def test_classify_roots() -> None:
    classification = classify_roots(CANONICAL_PATHS)

    assert "apps" in classification.source_roots
    assert "lore" in classification.source_roots
    assert "tests" in classification.test_roots
    assert "docs" in classification.docs_roots
    assert ".github" in classification.config_roots

    # Cross-checks: nothing appears in two categories
    all_classified = (
        classification.source_roots
        + classification.test_roots
        + classification.docs_roots
        + classification.config_roots
    )
    assert len(all_classified) == len(set(all_classified))


def test_classify_roots_config_root_names() -> None:
    paths = [
        "infra/terraform/main.tf",
        "k8s/deployment.yaml",
        "migrations/0001.py",
    ]
    c = classify_roots(paths)
    assert "infra" in c.config_roots
    assert "k8s" in c.config_roots
    assert "migrations" in c.config_roots
    # None of those should be source roots
    assert "infra" not in c.source_roots
    assert "k8s" not in c.source_roots


def test_classify_roots_src_is_source_root() -> None:
    """'src' is a common source root name and must be classified as source."""
    paths = ["src/main.py"]
    c = classify_roots(paths)
    assert "src" in c.source_roots


def test_classify_roots_results_sorted() -> None:
    paths = [
        "zzz_src/a.py",
        "aaa_src/b.py",
        "tests/c.py",
        "docs/d.md",
    ]
    c = classify_roots(paths)
    assert c.source_roots == sorted(c.source_roots)
    assert c.test_roots == sorted(c.test_roots)
    assert c.docs_roots == sorted(c.docs_roots)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_paths_returns_empty_sections() -> None:
    assert get_top_level_files([]) == []
    assert get_top_level_directories([]) == []
    assert detect_manifests([]) == []
    assert detect_entrypoint_candidates([]) == []
    infra = detect_infrastructure([])
    assert infra.docker_files == []
    assert infra.ci_files == []
    assert infra.migration_dirs == []
    c = classify_roots([])
    assert c.source_roots == []
    assert c.test_roots == []


def test_duplicate_paths_are_deduplicated() -> None:
    paths = ["README.md", "README.md", "src/app.py", "src/app.py"]
    files = get_top_level_files(paths)
    assert files.count("README.md") == 1
    dirs = get_top_level_directories(paths)
    assert len(dirs) == 1
    # Duplicate paths are collapsed: "src/app.py" appears twice but counts as one file.
    assert dirs[0].files == 1


def test_paths_are_sorted_deterministically() -> None:
    """Output must not depend on input order."""
    paths_a = ["lore/b.py", "apps/main.py", "README.md", "pyproject.toml"]
    paths_b = ["README.md", "pyproject.toml", "apps/main.py", "lore/b.py"]

    assert get_top_level_files(paths_a) == get_top_level_files(paths_b)
    assert get_top_level_directories(paths_a) == get_top_level_directories(paths_b)
    assert detect_manifests(paths_a) == detect_manifests(paths_b)
    assert detect_entrypoint_candidates(paths_a) == detect_entrypoint_candidates(paths_b)
```

- [ ] **Step 2: Run — confirm ImportError (module not yet created)**

```bash
uv run pytest tests/unit/artifacts/test_repository_structure_models.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'lore.artifacts.repository_structure_models'`

---

## Task 3: Implement models file with dataclasses and pure functions

**Files:**
- Create: `lore/artifacts/repository_structure_models.py`

- [ ] **Step 1: Create the file**

```python
# lore/artifacts/repository_structure_models.py
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RepositoryStructureState = Literal["missing", "fresh", "stale"]

_SOURCE_EXTENSIONS_FOR_ROOTS: frozenset[str] = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".java", ".cs", ".rs", ".rb", ".php", ".kt", ".swift",
})

_COMMON_SOURCE_ROOT_NAMES: frozenset[str] = frozenset({
    "src", "app", "apps", "lib", "libs", "packages", "services",
})

_DOCS_ROOTS: frozenset[str] = frozenset({"docs", "doc", "documentation"})
_TEST_ROOTS: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_CONFIG_ROOTS: frozenset[str] = frozenset({
    ".github", ".gitlab", ".circleci",
    "config", "configs", "infra", "deploy", "deployment",
    "k8s", "kubernetes", "migrations", "alembic",
})

_MANIFEST_BASENAMES: dict[str, str] = {
    "pyproject.toml": "python.project",
    "requirements.txt": "python.requirements",
    "poetry.lock": "python.poetry_lock",
    "Pipfile": "python.pipfile",
    "package.json": "node.package",
    "package-lock.json": "node.npm_lock",
    "pnpm-lock.yaml": "node.pnpm_lock",
    "yarn.lock": "node.yarn_lock",
    "Cargo.toml": "rust.cargo",
    "go.mod": "go.module",
    "pom.xml": "java.maven",
    "build.gradle": "java.gradle",
    "settings.gradle": "java.gradle_settings",
    "build.gradle.kts": "java.gradle_kts",
    "Gemfile": "ruby.gemfile",
    "composer.json": "php.composer",
}

_DOCKER_BASENAMES: frozenset[str] = frozenset({
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
})


@dataclass(frozen=True)
class RepositoryStructureRepositoryInfo:
    name: str
    full_name: str
    provider: str
    default_branch: str
    url: str


@dataclass(frozen=True)
class RepositoryStructureSyncInfo:
    sync_run_id: str
    last_synced_at: str | None
    commit_sha: str | None = None


@dataclass(frozen=True)
class TopLevelDirectoryEntry:
    path: str
    files: int


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    kind: str


@dataclass(frozen=True)
class EntrypointCandidate:
    path: str
    kind: str


@dataclass(frozen=True)
class RepositoryStructureTree:
    top_level_directories: list[TopLevelDirectoryEntry]
    top_level_files: list[str]


@dataclass(frozen=True)
class RepositoryStructureClassification:
    source_roots: list[str]
    test_roots: list[str]
    docs_roots: list[str]
    config_roots: list[str]


@dataclass(frozen=True)
class RepositoryStructureInfrastructure:
    docker_files: list[str]
    ci_files: list[str]
    migration_dirs: list[str]


@dataclass(frozen=True)
class RepositoryStructureStats:
    total_active_files: int
    top_level_directory_count: int
    manifest_count: int
    entrypoint_candidate_count: int


@dataclass(frozen=True)
class RepositoryStructureContent:
    repository: RepositoryStructureRepositoryInfo
    sync: RepositoryStructureSyncInfo
    tree: RepositoryStructureTree
    classification: RepositoryStructureClassification
    manifests: list[ManifestEntry]
    entrypoint_candidates: list[EntrypointCandidate]
    infrastructure: RepositoryStructureInfrastructure
    stats: RepositoryStructureStats
    schema_version: int = 1
    generated_by: str = "repository_structure_service"


# ---------------------------------------------------------------------------
# Pure classification functions
# ---------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    p = path.strip()
    if p.startswith("./"):
        p = p[2:]
    return p


def get_top_level_files(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        n = normalize_path(p)
        if not n or "/" in n:
            continue
        if n not in seen:
            seen.add(n)
            result.append(n)
    return sorted(result)


def get_top_level_directories(paths: list[str]) -> list[TopLevelDirectoryEntry]:
    # Deduplicate normalized paths before counting so repeated paths count as one file.
    unique = {normalize_path(p) for p in paths if normalize_path(p)}
    counts: dict[str, int] = {}
    for n in unique:
        if "/" not in n:
            continue
        top = n.split("/")[0]
        counts[top] = counts.get(top, 0) + 1
    return sorted(
        [TopLevelDirectoryEntry(path=d, files=c) for d, c in counts.items()],
        key=lambda e: e.path,
    )


def detect_manifests(paths: list[str]) -> list[ManifestEntry]:
    entries: dict[str, ManifestEntry] = {}
    for p in paths:
        n = normalize_path(p)
        if not n:
            continue
        kind = _MANIFEST_BASENAMES.get(Path(n).name)
        if kind is not None:
            entries[n] = ManifestEntry(path=n, kind=kind)
    return sorted(entries.values(), key=lambda e: e.path)


def _detect_entrypoint_kind(path: str) -> str | None:
    """Apply specific path rules before generic basename rules."""
    # Specific path-based rules first
    if path == "apps/api/main.py" or path.endswith("/api/main.py"):
        return "fastapi.app_candidate"
    if path == "src/index.ts" or path.endswith("/src/index.ts"):
        return "node.entry_candidate"
    if path == "src/main.ts" or path.endswith("/src/main.ts"):
        return "node.entry_candidate"
    if re.search(r"(^|/)cmd/[^/]+/main\.go$", path):
        return "go.main"
    # Generic basename rules
    basename = Path(path).name
    if basename == "main.py":
        return "python.main"
    if basename == "app.py":
        return "python.app"
    if basename == "manage.py":
        return "django.manage"
    if basename in ("server.js", "server.ts"):
        return "node.server"
    return None


def detect_entrypoint_candidates(paths: list[str]) -> list[EntrypointCandidate]:
    entries: dict[str, EntrypointCandidate] = {}
    for p in paths:
        n = normalize_path(p)
        if not n:
            continue
        kind = _detect_entrypoint_kind(n)
        if kind is not None:
            entries[n] = EntrypointCandidate(path=n, kind=kind)
    return sorted(entries.values(), key=lambda e: e.path)


def detect_infrastructure(paths: list[str]) -> RepositoryStructureInfrastructure:
    docker_files: set[str] = set()
    ci_files: set[str] = set()
    migration_dirs_set: set[str] = set()

    for p in paths:
        n = normalize_path(p)
        if not n:
            continue
        parts = n.split("/")
        basename = parts[-1]

        # Docker files — basename matching; use set for dedup
        if basename == "Dockerfile" or basename.startswith("Dockerfile.") or basename in _DOCKER_BASENAMES:
            docker_files.add(n)

        # CI files — path prefix matching (not basename); use set for dedup
        if n.startswith(".github/workflows/") and (n.endswith(".yml") or n.endswith(".yaml")):
            ci_files.add(n)
        elif n == ".gitlab-ci.yml":
            ci_files.add(n)
        elif n.startswith(".circleci/"):
            ci_files.add(n)

        # Migration dirs — scan directory components (exclude the filename)
        dir_parts = parts[:-1]
        for i, part in enumerate(dir_parts):
            if part in ("migrations", "alembic"):
                migration_dirs_set.add("/".join(parts[: i + 1]))

    return RepositoryStructureInfrastructure(
        docker_files=sorted(docker_files),
        ci_files=sorted(ci_files),
        migration_dirs=sorted(migration_dirs_set),
    )


def classify_roots(paths: list[str]) -> RepositoryStructureClassification:
    top_dirs: dict[str, list[str]] = {}
    for p in paths:
        n = normalize_path(p)
        if not n or "/" not in n:
            continue
        top = n.split("/")[0]
        top_dirs.setdefault(top, []).append(n)

    docs_roots: list[str] = []
    test_roots: list[str] = []
    config_roots: list[str] = []
    source_roots: list[str] = []

    for top, files in top_dirs.items():
        top_lower = top.lower()
        if top_lower in _DOCS_ROOTS:
            docs_roots.append(top)
        elif top_lower in _TEST_ROOTS:
            test_roots.append(top)
        elif top_lower in _CONFIG_ROOTS:
            config_roots.append(top)
        else:
            is_common_source = top_lower in _COMMON_SOURCE_ROOT_NAMES
            has_source_ext = any(
                Path(f).suffix.lower() in _SOURCE_EXTENSIONS_FOR_ROOTS for f in files
            )
            if is_common_source or has_source_ext:
                source_roots.append(top)

    return RepositoryStructureClassification(
        source_roots=sorted(source_roots),
        test_roots=sorted(test_roots),
        docs_roots=sorted(docs_roots),
        config_roots=sorted(config_roots),
    )
```

- [ ] **Step 2: Run unit tests**

```bash
make test-unit
```

Expected: all tests in `test_repository_structure_models.py` pass. Brief tests continue to pass.

- [ ] **Step 3: Commit**

```bash
git add lore/artifacts/repository_structure_models.py tests/unit/artifacts/test_repository_structure_models.py
git commit -m "feat: add RepositoryStructureContent models and path classification functions"
```

---

## Task 4: Write failing unit tests for RepositoryStructureService

**Files:**
- Create: `tests/unit/artifacts/test_repository_structure_service.py`

- [ ] **Step 1: Create the test file**

```python
# tests/unit/artifacts/test_repository_structure_service.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_structure_service import RepositoryStructureService
from lore.sync.errors import RepositoryNotFoundError
from tests.unit.artifacts._fakes import (
    FakeDocumentRepository,
    FakeExternalRepository,
    FakeExternalRepositoryRepository,
    FakeRepositoryArtifactRepository,
    FakeRepositorySyncRun,
    FakeRepositorySyncRunRepository,
)

pytestmark = pytest.mark.unit

_REPO_ID = uuid4()
_RUN_ID = uuid4()


def _make_repo(repo_id: UUID = _REPO_ID) -> FakeExternalRepository:
    return FakeExternalRepository(
        id=repo_id,
        name="lore",
        full_name="acme/lore",
        provider="github",
        default_branch="main",
        html_url="https://github.com/acme/lore",
    )


def _make_run(run_id: UUID = _RUN_ID, repo_id: UUID = _REPO_ID) -> FakeRepositorySyncRun:
    return FakeRepositorySyncRun(
        id=run_id,
        repository_id=repo_id,
        finished_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
    )


def _make_service(
    repo: FakeExternalRepository | None = None,
    run: FakeRepositorySyncRun | None = None,
    paths: list[str] | None = None,
    artifact_repo: FakeRepositoryArtifactRepository | None = None,
) -> tuple[RepositoryStructureService, FakeRepositoryArtifactRepository]:
    artifact_repo = artifact_repo or FakeRepositoryArtifactRepository()
    svc = RepositoryStructureService(
        external_repository_repo=FakeExternalRepositoryRepository(repo),  # type: ignore[arg-type]
        sync_run_repo=FakeRepositorySyncRunRepository(run),  # type: ignore[arg-type]
        document_repo=FakeDocumentRepository(paths or []),  # type: ignore[arg-type]
        artifact_repo=artifact_repo,  # type: ignore[arg-type]
    )
    return svc, artifact_repo


# ---------------------------------------------------------------------------
# generate_structure
# ---------------------------------------------------------------------------


async def test_generate_structure_creates_artifact_from_active_paths() -> None:
    paths = [
        "README.md",
        "pyproject.toml",
        "apps/api/main.py",
        "tests/unit/test_x.py",
    ]
    svc, artifact_repo = _make_service(repo=_make_repo(), run=_make_run(), paths=paths)
    result = await svc.generate_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False
    assert result.content is not None
    assert result.content.stats.total_active_files == 4
    assert result.content.stats.manifest_count == 1  # pyproject.toml
    assert result.content.stats.entrypoint_candidate_count == 1  # apps/api/main.py
    # Verify artifact was persisted via the public fake method
    persisted = await artifact_repo.get_by_repository_and_type(_REPO_ID, "repository_structure")
    assert persisted is not None
    assert persisted.artifact_type == "repository_structure"
    assert persisted.source_sync_run_id == _RUN_ID


async def test_generate_structure_empty_paths_is_valid() -> None:
    """A succeeded sync with zero active files must produce a fresh artifact."""
    svc, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=[])
    result = await svc.generate_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.content is not None
    assert result.content.stats.total_active_files == 0


async def test_generate_structure_raises_repository_not_found() -> None:
    svc, _ = _make_service(repo=None, run=_make_run())
    with pytest.raises(RepositoryNotFoundError):
        await svc.generate_structure(_REPO_ID)


async def test_generate_structure_raises_not_synced_without_successful_run() -> None:
    svc, _ = _make_service(repo=_make_repo(), run=None)
    with pytest.raises(RepositoryNotSyncedError):
        await svc.generate_structure(_REPO_ID)


# ---------------------------------------------------------------------------
# get_structure
# ---------------------------------------------------------------------------


async def test_get_structure_missing_returns_missing_state() -> None:
    svc, _ = _make_service(repo=_make_repo(), run=_make_run())
    # No artifact stored yet
    result = await svc.get_structure(_REPO_ID)

    assert result.exists is False
    assert result.state == "missing"
    assert result.reason == "structure_not_generated"
    assert result.content is None


async def test_get_structure_fresh_when_source_sync_matches_latest() -> None:
    run = _make_run()
    artifact_repo = FakeRepositoryArtifactRepository()
    svc, _ = _make_service(repo=_make_repo(), run=run, artifact_repo=artifact_repo)

    await svc.generate_structure(_REPO_ID)
    result = await svc.get_structure(_REPO_ID)

    assert result.exists is True
    assert result.state == "fresh"
    assert result.is_stale is False


async def test_get_structure_stale_when_latest_sync_differs() -> None:
    original_run = _make_run(run_id=uuid4())
    artifact_repo = FakeRepositoryArtifactRepository()

    svc_gen, _ = _make_service(repo=_make_repo(), run=original_run, artifact_repo=artifact_repo)
    await svc_gen.generate_structure(_REPO_ID)

    new_run = _make_run(run_id=uuid4())
    svc_get = RepositoryStructureService(
        external_repository_repo=FakeExternalRepositoryRepository(_make_repo()),  # type: ignore[arg-type]
        sync_run_repo=FakeRepositorySyncRunRepository(new_run),  # type: ignore[arg-type]
        document_repo=FakeDocumentRepository([]),  # type: ignore[arg-type]
        artifact_repo=artifact_repo,  # type: ignore[arg-type]
    )
    result = await svc_get.get_structure(_REPO_ID)

    assert result.is_stale is True
    assert result.state == "stale"
    assert result.current_sync_run_id == new_run.id


async def test_get_structure_deserializes_content_round_trip() -> None:
    paths = ["README.md", "apps/api/main.py", "tests/unit/test_x.py"]
    artifact_repo = FakeRepositoryArtifactRepository()
    svc, _ = _make_service(repo=_make_repo(), run=_make_run(), paths=paths, artifact_repo=artifact_repo)

    await svc.generate_structure(_REPO_ID)
    result = await svc.get_structure(_REPO_ID)

    assert result.content is not None
    assert result.content.stats.total_active_files == 3
    assert result.content.repository.full_name == "acme/lore"
    assert result.content.schema_version == 1
    assert result.content.generated_by == "repository_structure_service"


async def test_get_structure_raises_repository_not_found() -> None:
    svc, _ = _make_service(repo=None, run=_make_run())
    with pytest.raises(RepositoryNotFoundError):
        await svc.get_structure(_REPO_ID)
```

- [ ] **Step 2: Run — confirm ImportError (service module not yet created)**

```bash
uv run pytest tests/unit/artifacts/test_repository_structure_service.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'lore.artifacts.repository_structure_service'`

---

## Task 5: Implement RepositoryStructureService

**Files:**
- Create: `lore/artifacts/repository_structure_service.py`

- [ ] **Step 1: Create the file**

```python
# lore/artifacts/repository_structure_service.py
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from lore.artifacts.errors import RepositoryNotSyncedError
from lore.artifacts.repository_structure_models import (
    EntrypointCandidate,
    ManifestEntry,
    RepositoryStructureClassification,
    RepositoryStructureContent,
    RepositoryStructureInfrastructure,
    RepositoryStructureRepositoryInfo,
    RepositoryStructureState,
    RepositoryStructureStats,
    RepositoryStructureSyncInfo,
    RepositoryStructureTree,
    TopLevelDirectoryEntry,
    classify_roots,
    detect_entrypoint_candidates,
    detect_infrastructure,
    detect_manifests,
    get_top_level_directories,
    get_top_level_files,
    normalize_path,
)
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_STRUCTURE, RepositoryArtifact
from lore.sync.errors import RepositoryNotFoundError

if TYPE_CHECKING:
    from lore.infrastructure.db.repositories.document import DocumentRepository
    from lore.infrastructure.db.repositories.external_repository import (
        ExternalRepositoryRepository,
    )
    from lore.infrastructure.db.repositories.repository_artifact import (
        RepositoryArtifactRepository,
    )
    from lore.infrastructure.db.repositories.repository_sync_run import (
        RepositorySyncRunRepository,
    )


def _content_from_dict(d: dict) -> RepositoryStructureContent:  # type: ignore[type-arg]
    repo_info = d["repository"]
    sync_info = d["sync"]
    tree_info = d["tree"]
    cls_info = d["classification"]
    infra_info = d["infrastructure"]
    stats_info = d["stats"]
    return RepositoryStructureContent(
        repository=RepositoryStructureRepositoryInfo(
            name=repo_info["name"],
            full_name=repo_info["full_name"],
            provider=repo_info["provider"],
            default_branch=repo_info["default_branch"],
            url=repo_info["url"],
        ),
        sync=RepositoryStructureSyncInfo(
            sync_run_id=sync_info["sync_run_id"],
            last_synced_at=sync_info.get("last_synced_at"),
            commit_sha=sync_info.get("commit_sha"),
        ),
        tree=RepositoryStructureTree(
            top_level_directories=[
                TopLevelDirectoryEntry(path=e["path"], files=e["files"])
                for e in tree_info.get("top_level_directories", [])
            ],
            top_level_files=tree_info.get("top_level_files", []),
        ),
        classification=RepositoryStructureClassification(
            source_roots=cls_info.get("source_roots", []),
            test_roots=cls_info.get("test_roots", []),
            docs_roots=cls_info.get("docs_roots", []),
            config_roots=cls_info.get("config_roots", []),
        ),
        manifests=[
            ManifestEntry(path=e["path"], kind=e["kind"])
            for e in d.get("manifests", [])
        ],
        entrypoint_candidates=[
            EntrypointCandidate(path=e["path"], kind=e["kind"])
            for e in d.get("entrypoint_candidates", [])
        ],
        infrastructure=RepositoryStructureInfrastructure(
            docker_files=infra_info.get("docker_files", []),
            ci_files=infra_info.get("ci_files", []),
            migration_dirs=infra_info.get("migration_dirs", []),
        ),
        stats=RepositoryStructureStats(
            total_active_files=stats_info["total_active_files"],
            top_level_directory_count=stats_info["top_level_directory_count"],
            manifest_count=stats_info["manifest_count"],
            entrypoint_candidate_count=stats_info["entrypoint_candidate_count"],
        ),
        schema_version=d.get("schema_version", 1),
        generated_by=d.get("generated_by", "repository_structure_service"),
    )


@dataclass(frozen=True)
class RepositoryStructureServiceResult:
    exists: bool
    state: RepositoryStructureState
    is_stale: bool
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    generated_at: datetime | None = None
    source_sync_run_id: UUID | None = None
    current_sync_run_id: UUID | None = None
    content: RepositoryStructureContent | None = None
    reason: str | None = None


class RepositoryStructureService:
    def __init__(
        self,
        external_repository_repo: ExternalRepositoryRepository,
        sync_run_repo: RepositorySyncRunRepository,
        document_repo: DocumentRepository,
        artifact_repo: RepositoryArtifactRepository,
    ) -> None:
        self._ext_repo_repo = external_repository_repo
        self._sync_run_repo = sync_run_repo
        self._document_repo = document_repo
        self._artifact_repo = artifact_repo

    async def generate_structure(self, repository_id: UUID) -> RepositoryStructureServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)
        if latest_run is None:
            raise RepositoryNotSyncedError(repository_id)

        raw_paths = await self._document_repo.get_active_document_paths_by_repository_id(
            repository_id
        )
        normalized = sorted({normalize_path(p) for p in raw_paths if normalize_path(p)})

        tree = RepositoryStructureTree(
            top_level_directories=get_top_level_directories(normalized),
            top_level_files=get_top_level_files(normalized),
        )
        classification = classify_roots(normalized)
        manifests = detect_manifests(normalized)
        entrypoints = detect_entrypoint_candidates(normalized)
        infrastructure = detect_infrastructure(normalized)
        stats = RepositoryStructureStats(
            total_active_files=len(normalized),
            top_level_directory_count=len(tree.top_level_directories),
            manifest_count=len(manifests),
            entrypoint_candidate_count=len(entrypoints),
        )

        content = RepositoryStructureContent(
            repository=RepositoryStructureRepositoryInfo(
                name=repo.name,
                full_name=repo.full_name,
                provider=repo.provider,
                default_branch=repo.default_branch,
                url=repo.html_url,
            ),
            sync=RepositoryStructureSyncInfo(
                sync_run_id=str(latest_run.id),
                last_synced_at=latest_run.finished_at.isoformat()
                if latest_run.finished_at
                else None,
            ),
            tree=tree,
            classification=classification,
            manifests=manifests,
            entrypoint_candidates=entrypoints,
            infrastructure=infrastructure,
            stats=stats,
        )

        now = datetime.now(UTC)
        artifact = RepositoryArtifact(
            id=uuid4(),
            repository_id=repository_id,
            artifact_type=ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
            title=f"Repository Structure: {repo.full_name}",
            content_json=dataclasses.asdict(content),
            source_sync_run_id=latest_run.id,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        saved = await self._artifact_repo.upsert(artifact)

        return RepositoryStructureServiceResult(
            exists=True,
            state="fresh",
            is_stale=False,
            repository_id=repository_id,
            generated_at=saved.generated_at,
            source_sync_run_id=saved.source_sync_run_id,
            current_sync_run_id=latest_run.id,
            content=content,
        )

    async def get_structure(self, repository_id: UUID) -> RepositoryStructureServiceResult:
        repo = await self._ext_repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(repository_id)

        artifact = await self._artifact_repo.get_by_repository_and_type(
            repository_id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
        )
        if artifact is None:
            return RepositoryStructureServiceResult(
                exists=False,
                state="missing",
                is_stale=False,
                repository_id=repository_id,
                reason="structure_not_generated",
            )

        latest_run = await self._sync_run_repo.get_latest_succeeded_by_repository(repository_id)

        if latest_run is None:
            is_stale = True
            state: RepositoryStructureState = "stale"
            current_sync_run_id = None
        elif artifact.source_sync_run_id != latest_run.id:
            is_stale = True
            state = "stale"
            current_sync_run_id = latest_run.id
        else:
            is_stale = False
            state = "fresh"
            current_sync_run_id = latest_run.id

        content = _content_from_dict(artifact.content_json)

        return RepositoryStructureServiceResult(
            exists=True,
            state=state,
            is_stale=is_stale,
            repository_id=repository_id,
            generated_at=artifact.generated_at,
            source_sync_run_id=artifact.source_sync_run_id,
            current_sync_run_id=current_sync_run_id,
            content=content,
        )
```

- [ ] **Step 2: Run unit tests**

```bash
make test-unit
```

Expected: all tests in `test_repository_structure_service.py` and `test_repository_structure_models.py` pass.

- [ ] **Step 3: Commit**

```bash
git add lore/artifacts/repository_structure_service.py tests/unit/artifacts/test_repository_structure_service.py
git commit -m "feat: add RepositoryStructureService with generate/get/stale lifecycle"
```

---

## Task 6: Add Alembic migration 0006

**Files:**
- Create: `migrations/versions/0006_repository_structure_artifact_type.py`

- [ ] **Step 1: Create the migration**

```python
# migrations/versions/0006_repository_structure_artifact_type.py
"""repository_structure — expand artifact_type check constraint

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief', 'repository_structure')",
    )


def downgrade() -> None:
    # Delete repository_structure rows first — otherwise restoring the old constraint
    # (which only allows 'repository_brief') will fail due to existing rows.
    op.execute("DELETE FROM repository_artifacts WHERE artifact_type = 'repository_structure'")
    op.drop_constraint("ck_repository_artifact_type", "repository_artifacts", type_="check")
    op.create_check_constraint(
        "ck_repository_artifact_type",
        "repository_artifacts",
        "artifact_type IN ('repository_brief')",
    )
```

- [ ] **Step 2: Update RepositoryArtifactORM CheckConstraint**

Open `lore/infrastructure/db/models/repository_artifact.py`. Find `__table_args__` and update the `CheckConstraint`:

```python
# Change this:
CheckConstraint(
    "artifact_type IN ('repository_brief')",
    name="ck_repository_artifact_type",
),
# To this:
CheckConstraint(
    "artifact_type IN ('repository_brief', 'repository_structure')",
    name="ck_repository_artifact_type",
),
```

The `UniqueConstraint`, indexes, and `ForeignKeyConstraint`s remain unchanged.

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/0006_repository_structure_artifact_type.py lore/infrastructure/db/models/repository_artifact.py
git commit -m "feat: migration 0006 — expand repository_artifacts check constraint for repository_structure"
```

---

## Task 7: Write and run migration integration test

**Files:**
- Create: `tests/integration/test_migration_0006.py`

The integration test container uses `Base.metadata.create_all` (ORM DDL), not Alembic migrations. The test exercises the constraint by inserting rows with `RepositoryArtifactRepository.upsert()` — the practical behavioral check.

- [ ] **Step 1: Create the test file**

```python
# tests/integration/test_migration_0006.py
"""Verify repository_artifacts check constraint allows 'repository_structure'."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import sqlalchemy.exc

from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM
from lore.infrastructure.db.models.repository_sync_run import RepositorySyncRunORM
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.schema.repository_artifact import (
    ARTIFACT_TYPE_REPOSITORY_BRIEF,
    ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
    RepositoryArtifact,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _seed_repo_and_run(session: AsyncSession) -> tuple[ExternalRepositoryORM, RepositorySyncRunORM]:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]

    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(conn)
    await session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner="migorg",
        name=f"migrepo-{suffix}",
        full_name=f"migorg/migrepo-{suffix}",
        default_branch="main",
        html_url=f"https://github.com/migorg/migrepo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(repo)
    await session.flush()

    run = RepositorySyncRunORM(
        id=uuid4(),
        repository_id=repo.id,
        connector_id="github",
        trigger="manual",
        mode="full",
        status="succeeded",
        started_at=now,
        finished_at=now,
        warnings=[],
        metadata_={},
    )
    session.add(run)
    await session.flush()

    return repo, run


def _make_artifact(
    repository_id, sync_run_id, artifact_type: str
) -> RepositoryArtifact:
    now = datetime.now(UTC)
    return RepositoryArtifact(
        id=uuid4(),
        repository_id=repository_id,
        artifact_type=artifact_type,
        title=f"Test: {artifact_type}",
        content_json={"schema_version": 1},
        source_sync_run_id=sync_run_id,
        generated_at=now,
        created_at=now,
        updated_at=now,
    )


async def test_m_repository_structure_artifact_type_allowed(db_session: AsyncSession) -> None:
    """repository_structure artifact must persist without constraint violation."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    artifact = _make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE)
    saved = await artifact_repo.upsert(artifact)

    assert saved.artifact_type == ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    fetched = await artifact_repo.get_by_repository_and_type(
        repo.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    )
    assert fetched is not None
    assert fetched.source_sync_run_id == run.id


async def test_m_repository_brief_still_allowed(db_session: AsyncSession) -> None:
    """Existing repository_brief must still be accepted after constraint expansion."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    artifact = _make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_BRIEF)
    saved = await artifact_repo.upsert(artifact)

    assert saved.artifact_type == ARTIFACT_TYPE_REPOSITORY_BRIEF


async def test_m_both_types_coexist_for_same_repository(db_session: AsyncSession) -> None:
    """A single repository can have both artifact types simultaneously."""
    repo, run = await _seed_repo_and_run(db_session)
    artifact_repo = RepositoryArtifactRepository(db_session)

    await artifact_repo.upsert(_make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_BRIEF))
    await artifact_repo.upsert(_make_artifact(repo.id, run.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE))

    brief = await artifact_repo.get_by_repository_and_type(repo.id, ARTIFACT_TYPE_REPOSITORY_BRIEF)
    structure = await artifact_repo.get_by_repository_and_type(
        repo.id, ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    )
    assert brief is not None
    assert structure is not None
```

- [ ] **Step 2: Run migration integration test**

```bash
uv run pytest tests/integration/test_migration_0006.py -v -m integration
```

Expected: all 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_migration_0006.py
git commit -m "test: add migration 0006 integration tests for repository_structure constraint"
```

---

## Task 8: Add structure endpoints to repository_artifacts.py

**Files:**
- Modify: `apps/api/routes/v1/repository_artifacts.py`

- [ ] **Step 1: Add imports and response models**

Open `apps/api/routes/v1/repository_artifacts.py`. After the existing imports, add:

```python
# After existing imports, add:
from lore.artifacts.repository_structure_service import (
    RepositoryStructureService,
    RepositoryStructureServiceResult,
)
from lore.schema.repository_artifact import ARTIFACT_TYPE_REPOSITORY_STRUCTURE
```

The full modified file (existing content preserved, new additions marked):

```python
from __future__ import annotations

import dataclasses
from datetime import datetime  # noqa: TCH003
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID  # noqa: TCH003

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lore.artifacts.repository_brief_service import (
    RepositoryBriefService,
    RepositoryBriefServiceResult,
)
from lore.artifacts.repository_structure_service import (
    RepositoryStructureService,
    RepositoryStructureServiceResult,
)
from lore.infrastructure.db.repositories.document import DocumentRepository
from lore.infrastructure.db.repositories.external_repository import ExternalRepositoryRepository
from lore.infrastructure.db.repositories.repository_artifact import RepositoryArtifactRepository
from lore.infrastructure.db.repositories.repository_sync_run import RepositorySyncRunRepository
from lore.infrastructure.db.session import get_session
from lore.schema.repository_artifact import (
    ARTIFACT_TYPE_REPOSITORY_BRIEF,
    ARTIFACT_TYPE_REPOSITORY_STRUCTURE,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["repository-artifacts"])

SessionDep = Annotated["AsyncSession", Depends(get_session)]


# ---------------------------------------------------------------------------
# Brief — existing (do not change)
# ---------------------------------------------------------------------------


class RepositoryBriefMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "brief_not_generated"


class RepositoryBriefPresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: str = ARTIFACT_TYPE_REPOSITORY_BRIEF
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    brief: dict[str, Any]


def _build_brief_service(session: AsyncSession) -> RepositoryBriefService:
    return RepositoryBriefService(
        external_repository_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


def _to_response(
    result: RepositoryBriefServiceResult,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    if not result.exists:
        assert result.state == "missing"
        return RepositoryBriefMissingResponse(
            repository_id=result.repository_id,
            reason=result.reason or "brief_not_generated",
        )
    assert result.state in ("fresh", "stale")
    assert result.generated_at is not None
    assert result.source_sync_run_id is not None
    assert result.content is not None
    return RepositoryBriefPresentResponse(
        repository_id=result.repository_id,
        state=result.state,
        is_stale=result.is_stale,
        generated_at=result.generated_at,
        source_sync_run_id=result.source_sync_run_id,
        current_sync_run_id=result.current_sync_run_id,
        brief=dataclasses.asdict(result.content),
    )


@router.get("/repositories/{repository_id}/brief")
async def get_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefMissingResponse | RepositoryBriefPresentResponse:
    brief_service = _build_brief_service(session)
    result = await brief_service.get_brief(repository_id)
    return _to_response(result)


@router.post("/repositories/{repository_id}/brief/generate")
async def generate_repository_brief(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryBriefPresentResponse:
    brief_service = _build_brief_service(session)
    result = await brief_service.generate_brief(repository_id)
    await session.commit()
    return _to_response(result)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Structure — new endpoints
# ---------------------------------------------------------------------------


class RepositoryStructureMissingResponse(BaseModel):
    repository_id: UUID
    artifact_type: Literal["repository_structure"] = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = False
    state: Literal["missing"] = "missing"
    reason: str = "structure_not_generated"


class RepositoryStructurePresentResponse(BaseModel):
    repository_id: UUID
    artifact_type: Literal["repository_structure"] = ARTIFACT_TYPE_REPOSITORY_STRUCTURE
    exists: bool = True
    state: Literal["fresh", "stale"]
    is_stale: bool
    generated_at: datetime
    source_sync_run_id: UUID
    current_sync_run_id: UUID | None
    structure: dict[str, Any]


def _build_structure_service(session: AsyncSession) -> RepositoryStructureService:
    return RepositoryStructureService(
        external_repository_repo=ExternalRepositoryRepository(session),
        sync_run_repo=RepositorySyncRunRepository(session),
        document_repo=DocumentRepository(session),
        artifact_repo=RepositoryArtifactRepository(session),
    )


def _structure_to_response(
    result: RepositoryStructureServiceResult,
) -> RepositoryStructureMissingResponse | RepositoryStructurePresentResponse:
    if not result.exists:
        assert result.state == "missing"
        return RepositoryStructureMissingResponse(
            repository_id=result.repository_id,
            reason=result.reason or "structure_not_generated",
        )
    assert result.state in ("fresh", "stale")
    assert result.generated_at is not None
    assert result.source_sync_run_id is not None
    assert result.content is not None
    return RepositoryStructurePresentResponse(
        repository_id=result.repository_id,
        state=result.state,
        is_stale=result.is_stale,
        generated_at=result.generated_at,
        source_sync_run_id=result.source_sync_run_id,
        current_sync_run_id=result.current_sync_run_id,
        structure=dataclasses.asdict(result.content),
    )


@router.get("/repositories/{repository_id}/structure")
async def get_repository_structure(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryStructureMissingResponse | RepositoryStructurePresentResponse:
    svc = _build_structure_service(session)
    result = await svc.get_structure(repository_id)
    return _structure_to_response(result)


@router.post("/repositories/{repository_id}/structure/generate")
async def generate_repository_structure(
    repository_id: UUID,
    session: SessionDep,
) -> RepositoryStructurePresentResponse:
    svc = _build_structure_service(session)
    result = await svc.generate_structure(repository_id)
    await session.commit()
    return _structure_to_response(result)  # type: ignore[return-value]
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/routes/v1/repository_artifacts.py
git commit -m "feat: add GET/POST structure endpoints to repository_artifacts router"
```

---

## Task 9: Write and run API integration tests

**Files:**
- Create: `tests/integration/test_repository_structure_api.py`

These tests use a fake connector with `connector_id="fake-structure"`. Each test uses a unique `owner_suffix` (uuid4 slice) so tests don't interfere with each other. Error cases (`RepositoryNotFoundError` → 404, `RepositoryNotSyncedError` → 409) are handled by global exception handlers — no local handling needed.

- [ ] **Step 1: Create the test file**

```python
# tests/integration/test_repository_structure_api.py
"""API lifecycle tests for repository_structure artifact — tests A through F."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from lore.connector_sdk.base import BaseConnector
from lore.connector_sdk.capabilities import ConnectorCapabilities
from lore.connector_sdk.manifest import ConnectorManifest
from lore.connector_sdk.models import (
    CanonicalDocumentDraft,
    ExternalContainerDraft,
    FullSyncRequest,
    RawExternalObject,
    SyncResult,
)
from lore.connector_sdk.registry import ConnectorRegistry
from lore.connectors.github.normalizer import GitHubNormalizer
from lore.infrastructure.db.models.external_connection import ExternalConnectionORM
from lore.infrastructure.db.models.external_repository import ExternalRepositoryORM

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

CONNECTOR_ID = "fake-structure"

DEFAULT_PATHS = [
    "README.md",
    "pyproject.toml",
    "apps/api/main.py",
    "lore/ingestion/service.py",
    "tests/unit/test_service.py",
    "docs/index.md",
    ".github/workflows/ci.yml",
    "Dockerfile",
]


class _FakeStructureConnector(BaseConnector):
    def __init__(self, owner_suffix: str, paths: list[str] | None = None) -> None:
        self._suffix = owner_suffix
        self._paths = paths if paths is not None else DEFAULT_PATHS

    @property
    def _owner(self) -> str:
        return f"struct-org-{self._suffix}"

    @property
    def _repo(self) -> str:
        return f"struct-repo-{self._suffix}"

    @property
    def _full_name(self) -> str:
        return f"{self._owner}/{self._repo}"

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            connector_id=CONNECTOR_ID,
            display_name="Fake Structure",
            version="0.0.1",
            capabilities=ConnectorCapabilities(
                supports_full_sync=True,
                supports_incremental_sync=False,
                supports_webhooks=False,
                supports_repository_tree=False,
                supports_files=True,
                supports_issues=False,
                supports_pull_requests=False,
                supports_comments=False,
                supports_releases=False,
                supports_permissions=False,
                object_types=("github.file",),
            ),
        )

    async def inspect_resource(self, resource_uri: str) -> ExternalContainerDraft:
        return ExternalContainerDraft(
            provider=CONNECTOR_ID,
            owner=self._owner,
            name=self._repo,
            full_name=self._full_name,
            default_branch="main",
            html_url=f"https://example.com/{self._full_name}",
            visibility="public",
            metadata={},
        )

    async def full_sync(self, request: FullSyncRequest) -> SyncResult:
        raw_objects = []
        for path in self._paths:
            payload = {"path": path, "owner": self._owner, "repo": self._repo}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            content = f"# {path}"
            raw = RawExternalObject(
                provider=CONNECTOR_ID,
                object_type="github.file",
                external_id=f"{self._full_name}:file:{path}",
                external_url=f"https://example.com/{self._full_name}/blob/main/{path}",
                connection_id=request.connection_id,
                repository_id=request.repository_id,
                raw_payload=payload,
                raw_payload_hash="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                content=content,
                content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
                source_updated_at=None,
                fetched_at=datetime.now(UTC),
                metadata={
                    "path": path,
                    "owner": self._owner,
                    "repo": self._repo,
                    "branch": "main",
                },
            )
            raw_objects.append(raw)
        return SyncResult(connector_id=CONNECTOR_ID, raw_objects=raw_objects)

    def normalize(self, raw: RawExternalObject) -> list[CanonicalDocumentDraft]:
        return GitHubNormalizer().normalize(raw)


async def _import_repo(
    app: FastAPI,
    client: AsyncClient,
    suffix: str,
    paths: list[str] | None = None,
) -> UUID:
    connector = _FakeStructureConnector(owner_suffix=suffix, paths=paths)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(
        "/api/v1/repositories/import",
        json={
            "url": f"https://example.com/struct-org-{suffix}/struct-repo-{suffix}",
            "connector_id": CONNECTOR_ID,
        },
    )
    assert resp.status_code == 200, resp.text
    return UUID(resp.json()["repository_id"])


async def _sync_repo(
    app: FastAPI,
    client: AsyncClient,
    repo_id: UUID,
    suffix: str,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    connector = _FakeStructureConnector(owner_suffix=suffix, paths=paths)
    registry = ConnectorRegistry()
    registry.register(connector)
    app.state.connector_registry = registry
    resp = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def test_a_get_structure_missing_before_generation(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is False
    assert data["state"] == "missing"
    assert data["reason"] == "structure_not_generated"
    assert data["artifact_type"] == "repository_structure"


async def test_b_generate_structure_after_import(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    resp = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["exists"] is True
    assert data["state"] == "fresh"
    assert data["artifact_type"] == "repository_structure"
    assert data["is_stale"] is False

    structure = data["structure"]
    assert structure["stats"]["total_active_files"] == len(DEFAULT_PATHS)
    assert structure["stats"]["manifest_count"] == 1

    dir_paths = [e["path"] for e in structure["tree"]["top_level_directories"]]
    assert "apps" in dir_paths
    assert "lore" in dir_paths
    assert "tests" in dir_paths
    assert "docs" in dir_paths
    assert ".github" in dir_paths

    manifest_kinds = {m["path"]: m["kind"] for m in structure["manifests"]}
    assert manifest_kinds["pyproject.toml"] == "python.project"

    entrypoint_kinds = {e["path"]: e["kind"] for e in structure["entrypoint_candidates"]}
    assert entrypoint_kinds.get("apps/api/main.py") == "fastapi.app_candidate"

    assert "Dockerfile" in structure["infrastructure"]["docker_files"]
    assert ".github/workflows/ci.yml" in structure["infrastructure"]["ci_files"]

    assert "apps" in structure["classification"]["source_roots"]
    assert "lore" in structure["classification"]["source_roots"]
    assert "tests" in structure["classification"]["test_roots"]
    assert "docs" in structure["classification"]["docs_roots"]
    assert ".github" in structure["classification"]["config_roots"]


async def test_c_get_structure_fresh_after_generation(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)
    await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")

    resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert resp.status_code == 200
    data = resp.json()

    assert data["exists"] is True
    assert data["state"] == "fresh"
    assert data["is_stale"] is False
    assert data["artifact_type"] == "repository_structure"


async def test_d_structure_becomes_stale_after_new_successful_sync(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix)

    gen_resp = await app_client_with_db.post(
        f"/api/v1/repositories/{repo_id}/structure/generate"
    )
    assert gen_resp.status_code == 200
    source_sync_run_id = gen_resp.json()["source_sync_run_id"]

    await _sync_repo(app_with_db, app_client_with_db, repo_id, suffix)

    get_resp = await app_client_with_db.get(f"/api/v1/repositories/{repo_id}/structure")
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["state"] == "stale"
    assert data["is_stale"] is True
    assert data["current_sync_run_id"] != source_sync_run_id


async def test_e_structure_uses_only_active_documents(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
) -> None:
    suffix = str(uuid4())[:8]
    paths_sync1 = ["README.md", "apps/api/main.py"]
    paths_sync2 = ["README.md"]

    repo_id = await _import_repo(app_with_db, app_client_with_db, suffix, paths=paths_sync1)

    gen1 = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert gen1.status_code == 200
    s1 = gen1.json()["structure"]
    entry_paths_1 = [e["path"] for e in s1["entrypoint_candidates"]]
    assert "apps/api/main.py" in entry_paths_1
    assert s1["stats"]["total_active_files"] == 2

    await _sync_repo(app_with_db, app_client_with_db, repo_id, suffix, paths=paths_sync2)

    gen2 = await app_client_with_db.post(f"/api/v1/repositories/{repo_id}/structure/generate")
    assert gen2.status_code == 200
    s2 = gen2.json()["structure"]
    entry_paths_2 = [e["path"] for e in s2["entrypoint_candidates"]]
    assert "apps/api/main.py" not in entry_paths_2
    assert s2["stats"]["total_active_files"] == 1


async def test_f_generate_structure_without_succeeded_sync_returns_409(
    app_with_db: FastAPI,
    app_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:6]

    conn = ExternalConnectionORM(
        id=uuid4(),
        provider="github",
        auth_mode="env_pat",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    db_session.add(conn)
    await db_session.flush()

    repo = ExternalRepositoryORM(
        id=uuid4(),
        connection_id=conn.id,
        provider="github",
        owner=f"nosync-{suffix}",
        name=f"repo-{suffix}",
        full_name=f"nosync-{suffix}/repo-{suffix}",
        default_branch="main",
        html_url=f"https://example.com/nosync-{suffix}/repo-{suffix}",
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    db_session.add(repo)
    await db_session.flush()
    await db_session.commit()  # ensure row is visible to the route handler's session

    resp = await app_client_with_db.post(
        f"/api/v1/repositories/{repo.id}/structure/generate"
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "repository_not_synced"
```

- [ ] **Step 2: Run integration tests for structure API**

```bash
uv run pytest tests/integration/test_repository_structure_api.py -v -m integration
```

Expected: all 6 tests (A–F) pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_repository_structure_api.py
git commit -m "test: add repository structure API integration tests A-F"
```

---

## Task 10: Final validation

- [ ] **Step 1: Run full unit test suite**

```bash
make test-unit
```

Expected: all unit tests pass, including existing brief tests.

- [ ] **Step 2: Run full integration test suite**

```bash
make test-integration
```

Expected: all integration tests pass.

- [ ] **Step 3: Lint**

```bash
make lint
```

Expected: no issues.

- [ ] **Step 4: Type check**

```bash
make type-check
```

Expected: no errors in `lore/` or `apps/`.

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: address lint and type-check feedback"
```

Only if fixes were necessary. If everything passed clean, skip this step.
