from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RepositoryStructureState = Literal["missing", "fresh", "stale"]

_SOURCE_EXTENSIONS_FOR_ROOTS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".java",
        ".cs",
        ".rs",
        ".rb",
        ".php",
        ".kt",
        ".swift",
    }
)

_COMMON_SOURCE_ROOT_NAMES: frozenset[str] = frozenset(
    {
        "src",
        "app",
        "apps",
        "lib",
        "libs",
        "packages",
        "services",
    }
)

_DOCS_ROOTS: frozenset[str] = frozenset({"docs", "doc", "documentation"})
_TEST_ROOTS: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_CONFIG_ROOTS: frozenset[str] = frozenset(
    {
        ".github",
        ".gitlab",
        ".circleci",
        "config",
        "configs",
        "infra",
        "deploy",
        "deployment",
        "k8s",
        "kubernetes",
        "migrations",
        "alembic",
    }
)

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

_DOCKER_BASENAMES: frozenset[str] = frozenset(
    {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)


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
        if (
            basename == "Dockerfile"
            or basename.startswith("Dockerfile.")
            or basename in _DOCKER_BASENAMES
        ):
            docker_files.add(n)

        # CI files — path prefix matching (not basename); use set for dedup
        if (
            n.startswith(".github/workflows/")
            and (n.endswith(".yml") or n.endswith(".yaml"))
            or n == ".gitlab-ci.yml"
            or n.startswith(".circleci/")
        ):
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
