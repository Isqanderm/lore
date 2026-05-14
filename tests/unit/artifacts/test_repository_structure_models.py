# tests/unit/artifacts/test_repository_structure_models.py
from __future__ import annotations

import pytest

from lore.artifacts.repository_structure_models import (
    EntrypointCandidate,
    ManifestEntry,
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
    infra = detect_infrastructure(
        ["Dockerfile", "Dockerfile", ".github/workflows/ci.yml", ".github/workflows/ci.yml"]
    )
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
