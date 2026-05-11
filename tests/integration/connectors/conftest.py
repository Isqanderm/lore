"""Shared helpers for connector integration tests."""

from __future__ import annotations

import hashlib
import json


def canonical_hash(payload: dict) -> str:  # type: ignore[type-arg]
    """Return a sha256 hash of the JSON-canonical form of *payload*."""
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(serialised.encode()).hexdigest()


def content_hash(content: str) -> str:
    """Return a sha256 hash of *content*."""
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()
