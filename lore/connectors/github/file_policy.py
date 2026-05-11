from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


def _matches_any(path: str, patterns: list[str]) -> bool:
    """Check if path matches any pattern.

    Handles both direct fnmatch patterns and directory prefix patterns (ending with /**).
    """
    for pattern in patterns:
        # Direct fnmatch
        if fnmatch.fnmatch(path, pattern):
            return True
        # Check if any prefix of path matches "dir/**" patterns
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if path.startswith(prefix + "/"):
                return True
    return False


@dataclass
class FileSelectionPolicy:
    max_file_size_bytes: int = 500_000
    include_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_INCLUDES))
    exclude_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_EXCLUDES))

    def should_include(self, entry: GitHubTreeEntry) -> bool:
        """Determine whether a tree entry should be included for ingestion."""
        # Only include blobs (files), not trees (directories)
        if entry.type != "blob":
            return False

        # Exclude oversized files
        if entry.size is not None and entry.size > self.max_file_size_bytes:
            return False

        path = entry.path

        # Exclude patterns take priority
        if _matches_any(path, self.exclude_patterns):
            return False

        # Include if matches any include pattern
        return _matches_any(path, self.include_patterns)

    def filter(self, entries: list[GitHubTreeEntry]) -> list[GitHubTreeEntry]:
        """Filter a list of tree entries by policy."""
        return [e for e in entries if self.should_include(e)]
