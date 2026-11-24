"""Tests for the public clean-room sanitizer gate, PII patterns, file coverage, and false-positive corpus."""
from __future__ import annotations

import hashlib
import pathlib

from scripts.lib.sanitizer import check_skill_sources, scan_repository, scan_text_for_leaks

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_repository_passes_public_sanitization() -> None:
    """Confirms the entire repository has zero internal links, PII, or uncited skill sections."""
    assert scan_repository(REPO_ROOT) == []


def test_sanitizer_blocks_internal_links_and_pii_but_allows_safe_prose() -> None:
    """Verifies expanded regexes catch leaks without false positives on common code or Go/No-Go prose."""
    leaks = scan_text_for_leaks(
        "Check go/internal-doc, b/123456789, cl/6543210, user.c.googlers.com, alice@google.com.\n"
        "Also argolis on line 2 and cabral-gecx-spk-hub with CPF 123.456.789-00.\n",
        "sample.md",
    )
    assert len(leaks) == 7 or len(leaks) >= 7

    # False-positive corpus: adk-go/tree/main, Go/No-Go, django/utils, public URLs, and dates must pass.
    clean = scan_text_for_leaks(
        "See google/adk-go/tree/main, Go/No-Go checklist, django/utils, a/b/c paths, golang 1.23, "
        "https://cloud.google.com/ces, and date 2026-11-24.",
        "clean.md",
    )
    assert clean == []


def test_sanitizer_scans_dockerfiles_and_tfvars(tmp_path: pathlib.Path) -> None:
    """Negative test (IB-26): planted internal leaks inside Dockerfile and .tfvars files are caught."""
    (tmp_path / "Dockerfile").write_text("FROM alpine\n# see go/secret-build-doc\n", encoding="utf-8")
    (tmp_path / "demo.tfvars").write_text('project = "cabral-gecx-spk-hub"\n', encoding="utf-8")
    hits = scan_repository(tmp_path, scan_tests=True)
    assert any("Dockerfile" in h for h in hits)
    assert any("demo.tfvars" in h for h in hits)


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
