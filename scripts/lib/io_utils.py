"""Deterministic file I/O and hashing helpers for factory scripts.

Provides lazy YAML/JSON loaders and SHA-256 tree hashing without global side effects.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import yaml


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Loads a YAML file and verifies that the root node is a mapping."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def load_json(path: pathlib.Path) -> dict[str, Any]:
    """Loads a JSON file and verifies that the root node is an object."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def sha256_bytes(data: bytes) -> str:
    """Computes the lowercase hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    """Computes the lowercase hex SHA-256 digest of a single file."""
    return sha256_bytes(path.read_bytes())


def sha256_tree(root: pathlib.Path) -> str:
    """Computes a reproducible SHA-256 digest over all files inside root."""
    h = hashlib.sha256()
    if not root.exists():
        return h.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
