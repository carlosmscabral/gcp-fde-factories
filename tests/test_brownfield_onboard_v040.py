"""Tests for v0.4.0 dynamic brownfield onboarding (scanner, Readiness Gate, emitter, and drift)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

from scripts.lib.budget_engine import check_context_budget
from scripts.lib.onboard_emitter import END_MARKER, START_MARKER, check_readiness, emit_layer3_overlay
from scripts.lib.onboard_scanner import detect_repo_drift, scan_repository_facts
from scripts.lib.schema_validator import validate_yaml_file

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_SCHEMA = REPO_ROOT / "schemas/factory-profile.schema.json"
HUB_PROJECT_SCHEMA = REPO_ROOT / "schemas/hub-project.schema.json"
GECX_TOOLCHAIN = REPO_ROOT / "packs/gecx/toolchain-manifest.json"


def _make_brownfield_repo(root: pathlib.Path) -> pathlib.Path:
    """Creates a realistic brownfield repository with Poetry, Ruff, Playwright, and existing AI docs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[tool.poetry]\nname = 'billing-bot'\n[tool.ruff]\nline-length = 100\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"devDependencies": {"playwright": "^1.50.0"}, "scripts": {"test": "playwright test"}}),
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Existing Team Rules\nNever force-push to develop.\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# Existing Claude Guide\nKeep PRs small.\n", encoding="utf-8")
    (root / ".cursorrules").write_text("Use strict typing.\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/develop\n", encoding="utf-8")
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "docs" / "adr" / "001-arch.md").write_text("# ADR 001\n", encoding="utf-8")
    return root


def _base_profile(scan: dict, track: str = "express") -> dict:
    """Builds a valid onboarding profile from static scanner output."""
    prof = {
        "schema_version": "1",
        "slug": "billing-bot",
        "pack": "gecx",
        "pack_version": "0.4.0",
        "track": track,
        "existing_hub": True,
        "mode": "sandbox-direct",
        "diversity_profile": "cross-vendor",
        "autonomy": "supervised",
        "git_flow": {
            "base_branch": scan["git_flow"]["base_branch"],
            "branch_pattern": "feat/<issue>-<slug>",
            "commit_convention": "conventional-commits",
            "ci_platform": scan["git_flow"]["ci_platform"],
            "pr_template": scan["git_flow"]["pr_template"],
        },
        "commands": scan["commands"],
        "detected_binaries": scan["detected_binaries"],
        "missing_binaries": scan["missing_binaries"],
        "heavy_test_binaries": scan["heavy_test_binaries"],
        "ai_files_detected": scan["ai_files_detected"],
        "knowledge_sources": scan["knowledge_sources"],
        "modernization_gaps": scan["modernization_gaps"],
    }
    if track == "complete":
        prof.update({
            "mission": "Automate billing support triage with deterministic audit trails.",
            "non_goals": ["No direct core banking ledger mutations."],
            "requirements": [
                {
                    "id": "REQ-001",
                    "summary": "Respond to invoice lookup within 5 seconds.",
                    "acceptance_criteria": ["Synthetic eval suite passes with 0 failures."],
                }
            ],
            "invariants": ["Never log customer tax identifiers in stdout or traces."],
            "evaluation_pyramid": {"l1_offline": "pytest -q", "l2_sandbox": "gecx_sandbox_gate.py"},
        })
    return prof


def test_brownfield_scanner_detects_six_dimensions_and_toolchain_delta(tmp_path: pathlib.Path) -> None:
    """Confirms scan_repository_facts detects binaries, heavy testers, AI files, git branch, and docs."""
    repo = _make_brownfield_repo(tmp_path / "bf")
    scan = scan_repository_facts(repo, GECX_TOOLCHAIN)

    assert "python" in scan["stacks"] and "node" in scan["stacks"]
    assert "poetry" in scan["missing_binaries"]
    assert "ruff" in scan["missing_binaries"]
    assert "playwright" in scan["heavy_test_binaries"]
    assert "playwright" not in scan["missing_binaries"]
    assert scan["git_flow"]["base_branch"] == "develop"
    assert {"AGENTS.md", "CLAUDE.md", ".cursorrules"}.issubset(set(scan["ai_files_detected"]))
    assert "docs/adr/001-arch.md" in scan["knowledge_sources"]


def test_readiness_gate_blocks_incomplete_profiles_and_passes_complete(tmp_path: pathlib.Path) -> None:
    """Confirms Readiness Gate rejects placeholder lint or missing Complete-track fields."""
    repo = _make_brownfield_repo(tmp_path / "bf")
    scan = scan_repository_facts(repo, GECX_TOOLCHAIN)

    express = _base_profile(scan, track="express")
    assert check_readiness(express, PROFILE_SCHEMA)["ready"] is True

    weak_complete = _base_profile(scan, track="express")
    weak_complete["track"] = "complete"
    rep = check_readiness(weak_complete, PROFILE_SCHEMA)
    assert rep["ready"] is False
    assert any("mission" in msg for msg in rep["missing_or_weak"])

    full_complete = _base_profile(scan, track="complete")
    assert check_readiness(full_complete, PROFILE_SCHEMA)["ready"] is True


def test_emitter_is_non_destructive_idempotent_and_conditional_dockerfile(tmp_path: pathlib.Path) -> None:
    """Confirms Layer 3 emitter preserves existing AI files, generates conditional Dockerfiles, and passes budget."""
    repo = _make_brownfield_repo(tmp_path / "bf")
    scan = scan_repository_facts(repo, GECX_TOOLCHAIN)
    profile = _base_profile(scan, track="complete")
    image_ref = "us-central1-docker.pkg.dev/demo/repo/scion-gecx-runtime@sha256:" + ("a" * 64)

    res1 = emit_layer3_overlay(repo, profile, image_ref, PROFILE_SCHEMA)
    assert res1["custom_dockerfile"] == ".factory/Dockerfile.customer"
    assert res1["tester_dockerfile"] == ".factory/Dockerfile.customer-tester"

    df_text = (repo / ".factory" / "Dockerfile.customer").read_text(encoding="utf-8")
    assert f"ARG PACK_IMAGE={image_ref}" in df_text
    assert "USER root" in df_text and "USER scion" in df_text
    assert "poetry" in df_text and "ruff" in df_text

    # Existing customer prose in AGENTS.md, CLAUDE.md, and .cursorrules must remain intact.
    agents_first = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "# Existing Team Rules" in agents_first
    assert START_MARKER in agents_first and END_MARKER in agents_first
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == "# Existing Claude Guide\nKeep PRs small.\n"
    assert (repo / ".cursorrules").read_text(encoding="utf-8") == "Use strict typing.\n"

    # Re-running emit must be idempotent (exactly one delimited block).
    emit_layer3_overlay(repo, profile, image_ref, PROFILE_SCHEMA)
    agents_second = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_second == agents_first
    assert agents_second.count(START_MARKER) == 1

    # Generated .factory/hub-project.yaml must validate cleanly and avoid skill collisions.
    hub_proj = repo / ".factory" / "hub-project.yaml"
    assert validate_yaml_file(hub_proj, HUB_PROJECT_SCHEMA) == []
    budget_errs, _ = check_context_budget(REPO_ROOT, REPO_ROOT / "packs/gecx", hub_proj)
    assert budget_errs == []

    # When zero missing binaries exist (greenfield), no Dockerfile.customer is emitted.
    gf = tmp_path / "gf"
    gf.mkdir()
    gf_prof = _base_profile(scan_repository_facts(gf, GECX_TOOLCHAIN), track="express")
    gf_prof["commands"]["lint"] = "ruff check ."
    gf_res = emit_layer3_overlay(gf, gf_prof, image_ref, PROFILE_SCHEMA)
    assert gf_res["custom_dockerfile"] is None
    assert not (gf / ".factory" / "Dockerfile.customer").exists()

    # Day-2 drift detector flags newly introduced binaries after onboarding.
    (repo / "go.mod").write_text("module example.com/billing\n", encoding="utf-8")
    drift = detect_repo_drift(repo, GECX_TOOLCHAIN)
    assert drift["drift_detected"] is True
    assert any("go" in n for n in drift["notes"])


def test_factory_onboard_cli_scan_and_check(tmp_path: pathlib.Path) -> None:
    """Confirms core-gcp-fde/scripts/factory_onboard.py scan and check subcommands work via CLI."""
    repo = _make_brownfield_repo(tmp_path / "cli-repo")
    scan_out = tmp_path / "scan.json"
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"),
            "scan",
            "--repo",
            str(repo),
            "--toolchain-manifest",
            str(GECX_TOOLCHAIN),
            "--out",
            str(scan_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    scan = json.loads(scan_out.read_text(encoding="utf-8"))
    prof_path = tmp_path / "profile.yaml"
    prof_path.write_text(yaml.safe_dump(_base_profile(scan, track="express")), encoding="utf-8")

    res_chk = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"),
            "check",
            "--profile",
            str(prof_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_chk.returncode == 0, res_chk.stderr
    assert json.loads(res_chk.stdout)["ready"] is True
