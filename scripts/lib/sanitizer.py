"""Public repository sanitization gate (Stage 2 of the two-stage clean-room pipeline).

Checks generic internal-link regexes, corp emails, PII patterns, salted n-gram hashes,
and mandatory `source:` citations on normative skills under packs/*/skills/.
Never stores Tier-C internal codenames or customer lists (those stay on Cloudtop pre-push only).
"""
from __future__ import annotations

import hashlib
import pathlib
import re

INTERNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "go_shortlink": re.compile(r"\bgo/[a-z0-9][a-z0-9_-]{1,}\b"),
    "buganizer_link": re.compile(r"\bb/\d{6,}\b"),
    "corp_domain": re.compile(r"\b[a-z0-9-]+\.corp\.google\.com\b", re.I),
    "google_email": re.compile(r"\b[A-Za-z0-9._%+-]+@google\.com\b", re.I),
    "google3_path": re.compile(r"(?:/google/src/files/|//depot/google3/)"),
}

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "cpf": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
}

SOURCE_LINE_RE = re.compile(r"^\s*-\s*source:\s*(https://\S+|canaries/\S+)\s*$")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".tf", ".tftpl", ".sh", ".py", ".txt"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".terraform", "dist", ".pytest_cache"}


def scan_text_for_leaks(
    text: str,
    rel_path: str,
    salted_ngram_hashes: set[str] | None = None,
    salt: str = "",
) -> list[str]:
    """Scans a single text payload for internal Google references, PII, and salted n-grams."""
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for label, pat in INTERNAL_PATTERNS.items():
            if pat.search(line):
                findings.append(f"{rel_path}:{line_no} matched prohibited internal pattern '{label}'.")
        for label, pat in PII_PATTERNS.items():
            if pat.search(line):
                findings.append(f"{rel_path}:{line_no} matched prohibited PII pattern '{label}'.")

    if salted_ngram_hashes:
        tokens = re.findall(r"[a-z0-9_-]+", text.lower())
        for i in range(max(0, len(tokens) - 2)):
            ngram = " ".join(tokens[i : i + 3])
            digest = hashlib.sha256(f"{salt}:{ngram}".encode("utf-8")).hexdigest()
            if digest in salted_ngram_hashes:
                findings.append(f"{rel_path}: matched blocked salted 3-gram hash {digest[:12]}.")

    return findings


def check_skill_sources(skill_md: pathlib.Path, rel_path: str) -> list[str]:
    """Verifies that every H2 section in a pack skill declares at least one `source:` line."""
    findings: list[str] = []
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    current_heading: str | None = None
    has_source = False

    for line in lines:
        if line.startswith("## "):
            if current_heading and not has_source:
                findings.append(f"{rel_path}: section '{current_heading}' lacks a '- source: <url|canaries/...>' citation.")
            current_heading = line[3:].strip()
            has_source = False
        elif SOURCE_LINE_RE.match(line):
            has_source = True

    if current_heading and not has_source:
        findings.append(f"{rel_path}: section '{current_heading}' lacks a '- source: <url|canaries/...>' citation.")
    return findings


def scan_repository(repo_root: pathlib.Path, scan_tests: bool = False) -> list[str]:
    """Scans repository files for public sanitization violations and missing skill citations."""
    findings: list[str] = []
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
        if path.suffix not in TEXT_SUFFIXES:
            continue

        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        findings.extend(scan_text_for_leaks(text, rel))

        if path.name == "SKILL.md" and (rel.startswith("packs/") or rel.startswith("core-gcp-fde/")):
            findings.extend(check_skill_sources(path, rel))

    return findings
