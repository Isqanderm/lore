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
    type: str  # "blob" | "tree"
    sha: str
    size: int | None  # None for trees


@dataclass(frozen=True)
class GitHubRepositoryTree:
    branch: str
    commit_sha: str  # head commit SHA — single source of truth for provenance
    tree_sha: str
    entries: list[GitHubTreeEntry]


_HTTPS_RE = re.compile(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
_SSH_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")


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
