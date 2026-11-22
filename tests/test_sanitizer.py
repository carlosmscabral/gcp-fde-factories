"""Tests for the public clean-room sanitizer gate, PII patterns, and false-positive corpus."""
from __future__ import annotations

import hashlib
import pathlib

from scripts.lib.sanitizer import check_skill_sources, scan_repository, scan_text_for_leaks

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_repository_passes_public_sanitization() -> None:
    """Confirms the entire repository has zero internal links, PII, or uncited skill sections."""
    assert scan_repository(REPO_ROOT) == []


def test_sanitizer_blocks_internal_links_and_pii_but_allows_safe_prose() -> None:
    """Verifies word-boundary regexes catch leaks without false positives on common code."""
    leaks = scan_text_for_leaks(
        "Check go/internal-doc and b/123456789 from alice@google.com with CPF 123.456.789-00.",
        "sample.md",
    )
    assert len(leaks) == 4

    # False-positive corpus: Go language paths, short b/ words, public URLs, and dates must pass.
    clean = scan_text_for_leaks(
        "Use django/utils and a/b/c paths, golang 1.23, https://cloud.google.com/ces, and date 2026-11-22.",
        "clean.md",
    )
    assert clean == []


def test_sanitizer_salted_ngram_detection() -> None:
    """Confirms salted 3-gram hash matching blocks forbidden internal phrases without exposing them."""
    salt = "public-salt-v1"
    target_hash = hashlib.sha256(f"{salt}:secret codename alpha".encode("utf-8")).hexdigest()
    hits = scan_text_for_leaks("Architecture uses secret codename alpha today.", "doc.md", {target_hash}, salt)
    assert len(hits) == 1


def test_skill_section_without_source_fails(tmp_path: pathlib.Path) -> None:
    """Confirms normative skill sections lacking a '- source:' citation are rejected."""
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Skill\n\n## Rule Without Source\n- Do something important.\n", encoding="utf-8")
    errs = check_skill_sources(skill, "packs/gecx/skills/x/SKILL.md")
    assert len(errs) == 1
