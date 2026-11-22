"""Dependency lockfile verifier enforcing 40-char Git SHAs and permissive OSS licenses.

Rejects floating @main, @HEAD, or unpinned gh:// URIs across skills.lock and pack files.
"""
from __future__ import annotations

import pathlib
import re

from scripts.lib.io_utils import load_yaml

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_LICENSES = {"MIT", "Apache-2.0"}
FLOATING_URI_RE = re.compile(
    r"(?:gh://[^\s\"']+(?!@[0-9a-f]{40}\b)|https://github\.com/[^\s\"']+/tree/(?:main|master|HEAD)\b)"
)


def verify_skills_lock(lock_path: pathlib.Path) -> list[str]:
    """Validates every entry in skills.lock for 40-char SHA, SHA-256 digest, and OSS license."""
    errors: list[str] = []
    data = load_yaml(lock_path)
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        return ["skills.lock must contain a non-empty 'skills' list."]

    seen_names: set[str] = set()
    for idx, entry in enumerate(skills):
        name = str(entry.get("name", f"index-{idx}"))
        if name in seen_names:
            errors.append(f"Duplicate skill name in skills.lock: '{name}'.")
        seen_names.add(name)

        commit = str(entry.get("commit", ""))
        if not SHA40_RE.match(commit):
            errors.append(f"Skill '{name}' commit '{commit}' is not a 40-char lowercase SHA.")

        pinned_uri = str(entry.get("pinned_uri", ""))
        if commit not in pinned_uri:
            errors.append(f"Skill '{name}' pinned_uri '{pinned_uri}' does not embed its 40-char SHA.")

        digest = str(entry.get("sha256", ""))
        if not SHA256_RE.match(digest):
            errors.append(f"Skill '{name}' sha256 '{digest}' is not a 64-char hex digest.")

        lic = str(entry.get("license", ""))
        if lic not in ALLOWED_LICENSES:
            errors.append(f"Skill '{name}' license '{lic}' is not in allowed set {sorted(ALLOWED_LICENSES)}.")

    return errors


def scan_for_floating_uris(root: pathlib.Path, exclude_files: set[str] | None = None) -> list[str]:
    """Scans YAML and Markdown files under root for floating @main/@HEAD or unpinned gh:// URIs."""
    errors: list[str] = []
    skip = exclude_files or set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in skip:
            continue
        if path.suffix not in {".yaml", ".yml", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), 1):
            if "upstream_uri:" in line:
                continue
            if "gh://" in line:
                for token in re.findall(r"gh://[^\s\"'`]+", line):
                    if not re.search(r"@[0-9a-f]{40}$", token):
                        errors.append(f"{path}:{line_no} contains unpinned gh:// URI: {token}")
            if re.search(r"https://github\.com/[^\s\"'`]+/tree/(?:main|master|HEAD)\b", line):
                errors.append(f"{path}:{line_no} contains floating GitHub tree/main or HEAD URL.")
    return errors
