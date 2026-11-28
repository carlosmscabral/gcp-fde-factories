"""Regression tests for HC-05 findings (HC05-F1..F6) and ADR-015 cognitive brownfield onboarding.

Verifies dynamic Billing Budget all_updates_rule (DRS toggle), GKE Secure Boot prerequisite,
untrusted workspace hook and AI divergence advisory detection, git_flow.has_codeowners schema
parity, idempotent .scion/agents/ .gitignore insertion, ADR-014 Dockerfile single-line uv.lock*
COPY, and advisory-default vs --strict validate-dockerfile behavior for arbitrary binaries (e.g. nx).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from scripts.lib.dockerfile_recipes import validate_customer_dockerfile
from scripts.lib.onboard_emitter import check_readiness, emit_layer3_overlay
from scripts.lib.onboard_scanner import scan_repository_facts

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ONBOARD_CLI = REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"
PROFILE_SCHEMA = REPO_ROOT / "schemas/factory-profile.schema.json"
GECX_TOOLCHAIN = REPO_ROOT / "packs/gecx/toolchain-manifest.json"


def test_hc05_f1_finops_uses_dynamic_all_updates_rule_and_f2_secure_boot_doc() -> None:
    """Locks in HC05-F1 (dynamic all_updates_rule under DRS) and HC05-F2 (GKE --shielded-secure-boot)."""
    finops_tf = (REPO_ROOT / "deploy/01-landing-zone/finops.tf").read_text(encoding="utf-8")
    assert 'dynamic "all_updates_rule"' in finops_tf
    assert "for_each = var.enable_budget_pubsub_topic ? [1] : []" in finops_tf

    prereqs = (REPO_ROOT / "deploy/ENTERPRISE_PREREQUISITES.md").read_text(encoding="utf-8")
    assert "constraints/compute.requireShieldedVm" in prereqs
    assert "--shielded-secure-boot" in prereqs


def test_hc05_f6_adk_dockerfile_folds_optional_uv_lock_with_existing_files() -> None:
    """Locks in HC05-F6: no standalone wildcard COPY uv.lock* line in packs/adk/repo-scaffold/Dockerfile."""
    df_lines = (REPO_ROOT / "packs/adk/repo-scaffold/Dockerfile").read_text(encoding="utf-8").splitlines()
    copy_lines = [ln.strip() for ln in df_lines if ln.strip().upper().startswith("COPY ")]
    uv_lock_copies = [ln for ln in copy_lines if "uv.lock*" in ln]
    assert len(uv_lock_copies) == 1
    assert "pyproject.toml" in uv_lock_copies[0]


def test_hc05_f3_f4_f5_scanner_hooks_divergence_schema_and_gitignore(tmp_path: pathlib.Path) -> None:
    """Locks in HC05-F3 (hooks/AI divergence), HC05-F4 (has_codeowners schema), and HC05-F5 (.gitignore)."""
    repo = tmp_path / "hostile-bf"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["cxas-scrapi"]\n[tool.ruff]\n', encoding="utf-8")
    (repo / "AGENTS.md").write_bytes(b"# Team A\r\nRule 1\r\n")
    (repo / "CLAUDE.md").write_text("# Team B\nDifferent rule\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text('{"hooks": {"PostToolUse": []}}\n', encoding="utf-8")
    (repo / ".githooks").mkdir()
    (repo / ".githooks/pre-commit").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")

    scan = scan_repository_facts(repo, GECX_TOOLCHAIN)
    assert ".claude/settings.json" in scan["untrusted_hooks_detected"]
    assert ".githooks/pre-commit" in scan["untrusted_hooks_detected"]
    assert scan["ai_file_divergence"] == ["AGENTS.md", "CLAUDE.md"]
    codes = {f["code"] for f in scan["advisory_findings"]}
    assert {"UNTRUSTED_WORKSPACE_HOOKS", "AI_INSTRUCTION_DIVERGENCE"} <= codes
    gap_ids = {g["id"] for g in scan["modernization_gaps"]}
    assert {"GAP-UNTRUSTED-HOOKS", "GAP-AI-DIVERGENCE"} <= gap_ids

    # HC05-F4: scan["git_flow"] (including has_codeowners) passes factory-profile.schema.json directly.
    profile = {
        "schema_version": "1",
        "slug": "hostile-bf",
        "pack": "gecx",
        "pack_version": "0.4.0",
        "track": "express",
        "existing_hub": True,
        "mode": "sandbox-direct",
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": scan["git_flow"],
        "commands": scan["commands"],
        "detected_binaries": scan["detected_binaries"],
        "missing_binaries": scan["missing_binaries"],
        "heavy_test_binaries": scan["heavy_test_binaries"],
        "ai_files_detected": scan["ai_files_detected"],
        "knowledge_sources": scan["knowledge_sources"],
        "modernization_gaps": scan["modernization_gaps"],
    }
    report = check_readiness(profile, PROFILE_SCHEMA)
    assert report["ready"] is True, report

    # Wave 1 BG-C2: untrusted workspace hazards now fail closed until explicitly acknowledged.
    img = "us-central1-docker.pkg.dev/demo/repo/gecx-runtime@sha256:" + ("c" * 64)
    try:
        emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA)
        raise AssertionError("Expected emit_layer3_overlay to block on unacknowledged workspace hazards")
    except ValueError as exc:
        assert "Blocking untrusted workspace hazards" in str(exc)

    # HC05-F5: once hazards are acknowledged, emit_layer3_overlay adds .scion/agents/ to .gitignore idempotently.
    res = emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA, acknowledge_hazards=True)
    assert ".gitignore" in res["emitted_files"]
    gi = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".scion/agents/" in gi

    # Second emit is idempotent and does not duplicate .scion/agents/.
    res2 = emit_layer3_overlay(repo, profile, img, PROFILE_SCHEMA, acknowledge_hazards=True)
    assert ".gitignore" not in res2["emitted_files"]
    assert (repo / ".gitignore").read_text(encoding="utf-8").count(".scion/agents/") == 1


def test_adr015_validate_dockerfile_advisory_default_vs_strict_and_nx_custom_cli(tmp_path: pathlib.Path) -> None:
    """Locks in ADR-015: arbitrary binaries (nx) pass clean, risky patterns warn in advisory mode and fail in --strict."""
    digest = "us-central1-docker.pkg.dev/demo/repo/adk-runtime@sha256:" + ("d" * 64)

    # 1. Clean agent-authored Dockerfile for arbitrary monorepo CLI (nx) passes both advisory and --strict.
    clean_df = tmp_path / "Dockerfile.nx"
    clean_df.write_text(
        f"# Custom agent-authored Dockerfile for Nx monorepo\n"
        f"FROM {digest}\n"
        f"USER root\n"
        f"RUN npm install -g nx@20.4.0\n"
        f"USER scion\n"
        f"RUN nx --version\n",
        encoding="utf-8",
    )
    clean_adv = validate_customer_dockerfile(clean_df, strict=False)
    clean_strict = validate_customer_dockerfile(clean_df, strict=True)
    assert clean_adv["ok"] is True and clean_adv["advisory_findings"] == []
    assert clean_strict["ok"] is True

    # 2. Risky agent-authored Dockerfile (unpinned :latest, curl|sh, USER root) passes advisory (exit 0 with warnings) and fails --strict (exit 1).
    risky_df = tmp_path / "Dockerfile.risky"
    risky_df.write_text(
        "FROM us-central1-docker.pkg.dev/demo/repo/adk-runtime:latest\n"
        "USER root\n"
        "RUN curl -fsSL https://example.com/install.sh | bash\n",
        encoding="utf-8",
    )
    adv_proc = subprocess.run(
        [sys.executable, str(ONBOARD_CLI), "validate-dockerfile", "--dockerfile", str(risky_df), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert adv_proc.returncode == 0, adv_proc.stderr
    adv_json = json.loads(adv_proc.stdout)
    assert adv_json["ok"] is True and adv_json["mode"] == "advisory"
    codes = {f["code"] for f in adv_json["advisory_findings"]}
    assert {
        "BASE_IMAGE_NOT_DIGEST_PINNED",
        "SHELL_PIPE_INSTALL_DETECTED",
        "FINAL_STAGE_NON_ROOT_USER_MISSING",
    } <= codes

    strict_proc = subprocess.run(
        [sys.executable, str(ONBOARD_CLI), "validate-dockerfile", "--dockerfile", str(risky_df), "--strict", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict_proc.returncode == 1
    assert json.loads(strict_proc.stdout)["ok"] is False

    # 3. Structural corruption (no FROM) fails closed even in advisory mode.
    broken_df = tmp_path / "Dockerfile.broken"
    broken_df.write_text("RUN echo broken\n", encoding="utf-8")
    broken_res = validate_customer_dockerfile(broken_df, strict=False)
    assert broken_res["ok"] is False and broken_res["structural_errors"]

    # 4. Runtime PR security-auditor templates remain strict and untouched (explicit boundary).
    for pack in ("adk", "gecx"):
        sa_delta = (REPO_ROOT / f"packs/{pack}/templates/security-auditor/delta.md").read_text(encoding="utf-8")
        assert "report-only" not in sa_delta.lower()
        assert "advisory" not in sa_delta.lower()

    # 5. ADR-014 ADK Verdict Gate requires live verification on any non-docs runtime or dependency change (costela M5).
    wf = (REPO_ROOT / "packs/adk/repo-scaffold/.github/workflows/adk-verdict-gate.yml").read_text(encoding="utf-8")
    assert "git diff --no-renames --name-only" in wf
    assert "grep -Ev '^(README\\.md|docs/.*|.*\\.md|\\.factory/.*)$'" in wf


def test_hc07_f1_github_wif_pool_depends_on_project_services() -> None:
    """Locks in HC07-F1 (WIF pool service dependency) and HC07-F2 (adkSandboxDeployer revision read permissions)."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    marker = 'resource "google_iam_workload_identity_pool" "github_actions"'
    start = iam_tf.index(marker)
    block = iam_tf[start : iam_tf.index("\n}", start) + 2]
    assert "depends_on = [google_project_service.enabled]" in block

    deployer_marker = 'resource "google_project_iam_custom_role" "adk_sandbox_deployer"'
    d_start = iam_tf.index(deployer_marker)
    d_block = iam_tf[d_start : iam_tf.index("\n}", d_start) + 2]
    assert '"run.revisions.get"' in d_block
    assert '"run.revisions.list"' in d_block


