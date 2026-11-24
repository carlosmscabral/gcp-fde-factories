"""Public repository sanitization gate (Stage 2 of the two-stage clean-room pipeline).

Checks generic internal-link regexes, corp domains and emails, PII patterns, optional
workstation-only Tier-C denylist patterns loaded at runtime (never committed in source),
salted n-gram hashes, and mandatory `source:` citations on normative pack and core skills.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re

INTERNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "go_shortlink": re.compile(r"(?<![A-Za-z0-9_/-])go/(?!no-go\b)[A-Za-z0-9][A-Za-z0-9_-]{1,}\b", re.I),
    "buganizer_link": re.compile(r"(?<![A-Za-z0-9_/-])b/\d{5,}\b", re.I),
    "cl_link": re.compile(r"(?<![A-Za-z0-9_/-])cl/\d{6,}\b", re.I),
    "corp_domain": re.compile(r"\b[a-z0-9-]+\.corp\.google\.com\b", re.I),
    "googlers_host": re.compile(r"\b[a-z0-9-]+\.c\.googlers\.com\b", re.I),
    "google_email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?:corp\.)?google\.com\b", re.I),
    "google3_path": re.compile(r"(?:/google/src/files/|//depot/google3/)"),
}

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "cpf": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
}

SOURCE_LINE_RE = re.compile(r"^\s*-\s*source:\s*(https://\S+|canaries/\S+)\s*$")
TEXT_SUFFIXES = {
    ".md", ".yaml", ".yml", ".json", ".jsonl", ".html", ".tf", ".tftpl", ".tfvars",
    ".sh", ".py", ".txt", ".toml", ".lock", ".Dockerfile",
}
TEXT_FILENAMES = {"Dockerfile", "NOTICE", "Makefile", ".gitignore"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".terraform", "dist", ".pytest_cache"}


def _is_scannable_file(path: pathlib.Path) -> bool:
    """Returns True when path matches a scannable text suffix or exact filename."""
    return (
        path.suffix in TEXT_SUFFIXES
        or path.name in TEXT_FILENAMES
        or path.name.endswith(".Dockerfile")
        or path.name.endswith(".tfvars.example")
    )


def load_runtime_denylist(denylist_path: pathlib.Path | None = None) -> list[re.Pattern[str]]:
    """Loads optional untracked Tier-C denylist regexes from SANITIZER_DENYLIST_FILE or path."""
    target = denylist_path
    if target is None:
        env_path = os.environ.get("SANITIZER_DENYLIST_FILE", "").strip()
        target = pathlib.Path(env_path) if env_path else None
    if not (target and target.is_file()):
        return []
    patterns: list[re.Pattern[str]] = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(re.escape(line), re.I))
    return patterns


def scan_text_for_leaks(
    text: str,
    rel_path: str,
    salted_ngram_hashes: set[str] | None = None,
    salt: str = "",
    extra_denylist: list[re.Pattern[str]] | None = None,
) -> list[str]:
    """Scans a single text payload for internal Google references, PII, denylist hits, and salted n-grams."""
    findings: list[str] = []
    denylist = load_runtime_denylist() if extra_denylist is None else extra_denylist
    for line_no, line in enumerate(text.splitlines(), 1):
        for label, pat in INTERNAL_PATTERNS.items():
            if pat.search(line):
                findings.append(f"{rel_path}:{line_no} matched prohibited internal pattern '{label}'.")
        for label, pat in PII_PATTERNS.items():
            if pat.search(line):
                findings.append(f"{rel_path}:{line_no} matched prohibited PII pattern '{label}'.")
        for idx, pat in enumerate(denylist, 1):
            if pat.search(line):
                findings.append(f"{rel_path}:{line_no} matched runtime Tier-C denylist rule #{idx}.")

    if salted_ngram_hashes:
        tokens = re.findall(r"[a-z0-9_-]+", text.lower())
        for i in range(max(0, len(tokens) - 2)):
            ngram = " ".join(tokens[i : i + 3])
            digest = hashlib.sha256(f"{salt}:{ngram}".encode("utf-8")).hexdigest()
            if digest in salted_ngram_hashes:
                findings.append(f"{rel_path}: matched blocked salted 3-gram hash {digest[:12]}.")

    return findings


def check_skill_sources(skill_md: pathlib.Path, rel_path: str) -> list[str]:
    """Verifies that every H2 section in a pack or core skill declares at least one `source:` line."""
    findings: list[str] = []
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    current_heading: str | None = None
    has_source = False

    for line in lines:
        if line.startswith("## "):
            if current_heading and not has_source:
                findings.append(
                    f"{rel_path}: section '{current_heading}' lacks a '- source: <url|canaries/...>' citation."
                )
            current_heading = line[3:].strip()
            has_source = False
        elif SOURCE_LINE_RE.match(line):
            has_source = True

    if current_heading and not has_source:
        findings.append(
            f"{rel_path}: section '{current_heading}' lacks a '- source: <url|canaries/...>' citation."
        )
    return findings


def scan_repository(
    repo_root: pathlib.Path,
    scan_tests: bool = False,
    denylist_path: pathlib.Path | None = None,
) -> list[str]:
    """Scans repository files for public sanitization violations and missing skill citations."""
    findings: list[str] = []
    extra_denylist = load_runtime_denylist(denylist_path)
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not scan_tests and rel_parts[0] == "tests":
            continue
        if path.name == "sanitizer.py":
            continue
        if not _is_scannable_file(path):
            continue

        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        findings.extend(scan_text_for_leaks(text, rel, extra_denylist=extra_denylist))

        if path.name == "SKILL.md" and (rel.startswith("packs/") or rel.startswith("core-gcp-fde/")):
            findings.extend(check_skill_sources(path, rel))

    return findings
