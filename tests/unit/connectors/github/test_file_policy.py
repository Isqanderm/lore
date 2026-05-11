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
