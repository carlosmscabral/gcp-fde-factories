"""Deterministic file I/O and hashing helpers for factory scripts.

Provides lazy YAML/JSON loaders and SHA-256 tree hashing without global side effects.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any

import yaml


def assert_no_symlink_escape(repo: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
    """Verifies target stays inside repo and no path component from repo to target is a symlink."""
    repo_root = repo.resolve()
    rel = target.relative_to(repo_root) if target.is_absolute() else target
    cur = repo_root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError(f"Refusing to traverse or write through symlink: {cur}")
    resolved = cur.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"Refusing path escaping repository root: {target}") from exc
    return cur


def assert_read_path_inside_repo(repo: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
    """Allows read-only access to in-repo symlinks while blocking any symlink escaping repo root."""
    repo_root = repo.resolve()
    raw_target = target if target.is_absolute() else (repo_root / target)
    resolved = raw_target.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"Refusing path escaping repository root: {target}") from exc
    return resolved


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    """Writes bytes via a same-directory temporary file and os.replace to prevent truncated writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


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
