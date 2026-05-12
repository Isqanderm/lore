from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MARKDOWN_EXTENSIONS: frozenset[str] = frozenset({".md", ".mdx"})

SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".py",
        ".go",
        ".java",
        ".cs",
        ".rs",
        ".rb",
        ".php",
        ".cpp",
        ".c",
        ".h",
        ".kt",
        ".swift",
    }
)

RepositoryBriefState = Literal["missing", "fresh", "stale"]


@dataclass(frozen=True)
class RepositoryBriefRepositoryInfo:
    name: str
    full_name: str
    provider: str
    default_branch: str
    url: str


@dataclass(frozen=True)
class RepositoryBriefSyncInfo:
    sync_run_id: str
    last_synced_at: str | None
    commit_sha: None = None


@dataclass(frozen=True)
class RepositoryBriefStats:
    total_files: int
    markdown_files: int
    source_files: int
    config_files: int
    test_files: int


@dataclass(frozen=True)
class LanguageEntry:
    extension: str
    count: int


@dataclass(frozen=True)
class ImportantFileEntry:
    path: str
    kind: str


@dataclass(frozen=True)
class RepositoryBriefSignals:
    has_readme: bool
    has_tests: bool
    has_docker: bool
    has_ci: bool
    has_package_manifest: bool


@dataclass(frozen=True)
class RepositoryBriefContent:
    repository: RepositoryBriefRepositoryInfo
    sync: RepositoryBriefSyncInfo
    stats: RepositoryBriefStats
    languages: list[LanguageEntry]
    important_files: list[ImportantFileEntry]
    signals: RepositoryBriefSignals
    schema_version: int = 1
    generated_by: str = "repository_brief_service"


def _is_config(path_str: str) -> bool:
    p = Path(path_str)
    name_lower = p.name.lower()
    exact_names = {
        "package.json",
        "tsconfig.json",
        "pyproject.toml",
        "requirements.txt",
        "poetry.lock",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        ".env.sample",
        ".env.dist",
    }
    if name_lower in exact_names:
        return True
    if name_lower.startswith("vite.config."):
        return True
    if name_lower.startswith("next.config."):
        return True
    if name_lower.startswith("eslint."):
        return True
    if name_lower.startswith("prettier."):
        return True
    parts_lower = [part.lower() for part in p.parts]
    return len(parts_lower) >= 3 and parts_lower[-3] == ".github" and parts_lower[-2] == "workflows"


def _is_test(path_str: str) -> bool:
    p = Path(path_str)
    test_dirs = {"test", "tests", "spec", "__tests__"}
    for part in p.parts[:-1]:
        if part.lower() in test_dirs:
            return True
    stem = p.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test")


def categorize_paths(paths: list[str]) -> RepositoryBriefStats:
    total = len(paths)
    markdown = source = config = test = 0
    for p in paths:
        ext = Path(p).suffix.lower()
        if ext in MARKDOWN_EXTENSIONS:
            markdown += 1
        if ext in SOURCE_EXTENSIONS:
            source += 1
        if _is_config(p):
            config += 1
        if _is_test(p):
            test += 1
    return RepositoryBriefStats(
        total_files=total,
        markdown_files=markdown,
        source_files=source,
        config_files=config,
        test_files=test,
    )


def _is_github_workflow(path_str: str) -> bool:
    p = Path(path_str)
    parts_lower = [part.lower() for part in p.parts]
    return len(parts_lower) >= 3 and parts_lower[-3] == ".github" and parts_lower[-2] == "workflows"


def detect_important_files(paths: list[str]) -> list[ImportantFileEntry]:
    results: list[ImportantFileEntry] = []
    for path_str in paths:
        p = Path(path_str)
        name_lower = p.name.lower()
        kind: str | None = None
        if name_lower in {"readme.md", "readme.rst", "readme.txt", "readme"}:
            kind = "readme"
        elif name_lower in {"package.json", "pyproject.toml", "requirements.txt"}:
            kind = "package_manifest"
        elif name_lower in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
            kind = "docker"
        elif name_lower == "tsconfig.json":
            kind = "ts_config"
        elif name_lower.startswith("eslint."):
            kind = "lint_config"
        elif name_lower in {".env.example", ".env.sample", ".env.dist"}:
            kind = "env_example"
        elif _is_github_workflow(path_str):
            kind = "ci_config"
        if kind is not None:
            results.append(ImportantFileEntry(path=path_str, kind=kind))
    return results


def detect_signals(
    important_files: list[ImportantFileEntry],
    stats: RepositoryBriefStats | None = None,
) -> RepositoryBriefSignals:
    kinds = {f.kind for f in important_files}
    has_tests = (stats.test_files > 0) if stats is not None else False
    return RepositoryBriefSignals(
        has_readme="readme" in kinds,
        has_tests=has_tests,
        has_docker="docker" in kinds,
        has_ci="ci_config" in kinds,
        has_package_manifest="package_manifest" in kinds,
    )


def get_language_counts(paths: list[str]) -> list[LanguageEntry]:
    counts: dict[str, int] = {}
    for path_str in paths:
        ext = Path(path_str).suffix.lower()
        if ext:
            counts[ext] = counts.get(ext, 0) + 1
    return sorted(
        [LanguageEntry(extension=ext, count=cnt) for ext, cnt in counts.items()],
        key=lambda e: (-e.count, e.extension),
    )
