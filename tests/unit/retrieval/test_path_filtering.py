from __future__ import annotations

import pytest

from lore.retrieval.service import _is_retrievable_repository_path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path",
    [
        "src/main.py",
        "lore/retrieval/service.py",
        "README.md",
        "docs/architecture.md",
        "tests/unit/test_service.py",
        "package.json",
        "pyproject.toml",
        "Dockerfile",
        ".github/workflows/ci.yml",
    ],
)
def test_is_retrievable_repository_path_allows_source_docs_and_config(path: str) -> None:
    assert _is_retrievable_repository_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/react/index.js",
        "frontend/dist/assets/app.js",
        "backend/build/generated.py",
        ".venv/lib/python/site-packages/x.py",
        "src/__pycache__/service.cpython-312.pyc",
        "coverage/index.html",
        ".next/server/app.js",
        ".pytest_cache/v/cache/nodeids",
        ".mypy_cache/3.12/module.meta.json",
        "target/debug/app",
        "lib/python3.12/site-packages/requests/__init__.py",
        "frontend/.parcel-cache/data.mdb",
        ".svelte-kit/generated/server.js",
    ],
)
def test_is_retrievable_repository_path_excludes_noise_directories(path: str) -> None:
    assert _is_retrievable_repository_path(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "package-lock.json",
        "frontend/pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "composer.lock",
        "Gemfile.lock",
        "src/app.min.js",
        "src/styles.min.css",
        "src/app.js.map",
        "assets/logo.png",
        "assets/photo.jpeg",
        "archive/release.zip",
        "static/font.woff2",
        "static/icon.ttf",
        "dist/module.wasm",
        "assets/compressed.br",
    ],
)
def test_is_retrievable_repository_path_excludes_noise_files(path: str) -> None:
    assert _is_retrievable_repository_path(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "src/distribution/service.py",
        "src/builders/factory.py",
        "vendor_profile/service.py",
        "src/node_modules_helper.py",
        "src/coverage_report/service.py",
        "src/outbound/client.py",
        # These prove filename exclusion is exact-match only, not suffix/substring on the full path
        "docs/poetry.lock.md",
        "src/package-lock.json.md",
    ],
)
def test_is_retrievable_repository_path_does_not_exclude_substring_matches(path: str) -> None:
    assert _is_retrievable_repository_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        r"NODE_MODULES\react\index.js",
        r"Frontend\DIST\app.js",
        r"SRC\APP.MIN.JS",
        r"Poetry.Lock",
    ],
)
def test_is_retrievable_repository_path_normalizes_case_and_separators(path: str) -> None:
    assert _is_retrievable_repository_path(path) is False


@pytest.mark.parametrize("path", ["", "   ", "/", "\\"])
def test_is_retrievable_repository_path_rejects_empty_paths(path: str) -> None:
    assert _is_retrievable_repository_path(path) is False
