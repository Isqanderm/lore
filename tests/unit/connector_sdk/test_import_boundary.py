"""
Verifies the import isolation invariant:
  lore.schema, lore.connector_sdk, lore.ingestion
  must NOT transitively import lore.connectors.github.
If this test fails, a boundary violation was introduced.
"""

import importlib
import sys


def _get_all_imported_modules(root_module: str) -> set[str]:
    """Import root_module and return the set of all sys.modules keys added."""
    before = set(sys.modules.keys())
    importlib.import_module(root_module)
    after = set(sys.modules.keys())
    return after - before


def test_schema_does_not_import_github() -> None:
    # Clear any cached imports for isolation
    to_remove = [k for k in sys.modules if k.startswith("lore.schema")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.schema")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert not github_imports, f"lore.schema transitively imports lore.connectors: {github_imports}"


def test_connector_sdk_does_not_import_github() -> None:
    to_remove = [k for k in sys.modules if k.startswith("lore.connector_sdk")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.connector_sdk")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert (
        not github_imports
    ), f"lore.connector_sdk transitively imports lore.connectors: {github_imports}"


def test_ingestion_does_not_import_github() -> None:
    to_remove = [k for k in sys.modules if k.startswith("lore.ingestion")]
    for k in to_remove:
        del sys.modules[k]

    new_modules = _get_all_imported_modules("lore.ingestion")
    github_imports = {m for m in new_modules if "lore.connectors" in m}
    assert (
        not github_imports
    ), f"lore.ingestion transitively imports lore.connectors: {github_imports}"
