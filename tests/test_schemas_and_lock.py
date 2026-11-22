"""Tests for Contract 1 (pack.yaml), compat.yaml, hub-project.yaml, and skills.lock."""
from __future__ import annotations

import pathlib

import yaml

from scripts.lib.lock_verifier import scan_for_floating_uris, verify_skills_lock
from scripts.lib.schema_validator import validate_against_schema, validate_yaml_file

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gecx_pack_and_compat_validate_cleanly() -> None:
    """Confirms packs/gecx/pack.yaml, compat.yaml, and hub-project.yaml pass schema checks."""
    assert validate_yaml_file(REPO_ROOT / "packs/gecx/pack.yaml", REPO_ROOT / "schemas/pack.schema.json") == []
    assert validate_yaml_file(REPO_ROOT / "compat.yaml", REPO_ROOT / "schemas/compat.schema.json") == []
    assert (
        validate_yaml_file(
            REPO_ROOT / "packs/gecx/repo-scaffold/.factory/hub-project.yaml",
            REPO_ROOT / "schemas/hub-project.schema.json",
        )
        == []
    )


def test_compat_rejects_range_operator() -> None:
    """Confirms compat.schema.json rejects '>=v0.4.0' version ranges (closed list only)."""
    cfg = yaml.safe_load((REPO_ROOT / "compat.yaml").read_text(encoding="utf-8"))
    cfg["scion"]["tested"] = [">=v0.4.0"]
    errs = validate_against_schema(cfg, REPO_ROOT / "schemas/compat.schema.json")
    assert errs


def test_skills_lock_validates_all_pinned_shas() -> None:
    """Confirms every entry in skills.lock holds a 40-char SHA, SHA-256 digest, and OSS license."""
    assert verify_skills_lock(REPO_ROOT / "skills.lock") == []


def test_floating_uri_scanner_blocks_unpinned_gh_and_tree_main(tmp_path: pathlib.Path) -> None:
    """Confirms floating gh:// URIs and tree/main URLs are caught deterministically."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("skills:\n  - gh://addyosmani/agent-skills/code-review\n  - https://github.com/org/repo/tree/main/x\n")
    errs = scan_for_floating_uris(tmp_path)
    assert len(errs) == 2
