"""Adversarial regression tests locking in all v0.6.0 (contrafile) cross-vendor review fixes.

Covers C1, H1-H7, M1-M8, and L1-L6: Scion v0.4.0-preview.3 CLI contract snapshot validation,
fail-closed coordinator idempotency, v0.5.0 non-regression, symlink escape refusal and atomic
emit, custom Dockerfile preservation, Rust/Gradle test commands, hardened kp-check, L1 env
allowlist, L2 fail-closed, generic Cloud Run janitor, CORE_VERSION=0.6.0, and Stage 01 toggles.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import shlex
import stat
import subprocess
import sys

import pytest
import yaml

from scripts.lib.onboard_emitter import check_readiness, emit_layer3_overlay
from scripts.lib.onboard_kp import check_knowledge_plane
from scripts.lib.onboard_questions import _sanitize_slug, build_draft_profile
from scripts.lib.onboard_scanner import scan_repository_facts
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_SCHEMA = REPO_ROOT / "schemas/factory-profile.schema.json"
GENERIC_TOOLCHAIN = REPO_ROOT / "packs/generic/toolchain-manifest.json"
SCION_CONTRACT = REPO_ROOT / "canaries/scion/scion_v0.4.0-preview.3_cli_contract.json"


def _load_module(name: str, path: pathlib.Path):
    """Loads a standalone script module by file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _minimal_profile(slug: str = "safe-repo", pack: str = "generic", deploy_target: str = "none") -> dict:
    """Returns a minimal valid express profile for security and emitter tests."""
    return {
        "schema_version": "1",
        "slug": slug,
        "pack": pack,
        "pack_version": "0.6.0",
        "track": "express",
        "existing_hub": True,
        "mode": "ci-only",
        "deploy_target": deploy_target,
        "diversity_profile": "cross-model",
        "autonomy": "supervised",
        "git_flow": {
            "base_branch": "main",
            "branch_pattern": "feat/<issue>-<slug>",
            "commit_convention": "conventional-commits",
            "ci_platform": "none",
            "pr_template": None,
            "workflows": [],
            "has_codeowners": False,
        },
        "commands": {"build": "", "lint": "ruff check .", "test": "pytest -q", "e2e": ""},
        "detected_binaries": ["python", "ruff"],
        "missing_binaries": ["ruff"],
        "heavy_test_binaries": [],
        "ai_files_detected": [],
        "knowledge_sources": ["README.md"],
        "modernization_gaps": [],
    }


def test_h4_m1_m2_symlink_refusal_atomic_emit_and_custom_dockerfile_preservation(tmp_path: pathlib.Path) -> None:
    """Locks in H4 (symlink escapes), M1 (no partial writes), and M2 (custom Dockerfile preserved)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    img = "us-central1-docker.pkg.dev/demo/repo/generic-runtime@sha256:" + ("a" * 64)

    # 1. Symlinked .factory directory must fail before writing anything outside repo.
    r1 = tmp_path / "r-factory-link"
    r1.mkdir()
    (r1 / "README.md").write_text("# R1\n", encoding="utf-8")
    (r1 / ".factory").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        emit_layer3_overlay(r1, _minimal_profile(), img, PROFILE_SCHEMA)
    assert list(outside.iterdir()) == []

    # 2. Symlinked glossary.md must abort BEFORE creating SKILL.md or requirements.md (atomic M1).
    r2 = tmp_path / "r-atomic"
    (r2 / ".factory" / "knowledge").mkdir(parents=True)
    (r2 / "README.md").write_text("# R2\n", encoding="utf-8")
    victim = outside / "victim.md"
    victim.write_text("untouched\n", encoding="utf-8")
    (r2 / ".factory" / "knowledge" / "glossary.md").symlink_to(victim)
    with pytest.raises(ValueError, match="symlink"):
        emit_layer3_overlay(r2, _minimal_profile(), img, PROFILE_SCHEMA)
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    assert not (r2 / "skills" / "safe-repo-repo-conventions" / "SKILL.md").exists()
    assert not (r2 / ".factory" / "knowledge" / "requirements.md").exists()

    # 3. Symlinked hub-project.yaml must not be read or overwritten (H4).
    r3 = tmp_path / "r-hub-link"
    (r3 / ".factory").mkdir(parents=True)
    (r3 / "README.md").write_text("# R3\n", encoding="utf-8")
    victim_yaml = outside / "victim.yaml"
    victim_yaml.write_text("secret: keep\n", encoding="utf-8")
    (r3 / ".factory" / "hub-project.yaml").symlink_to(victim_yaml)
    with pytest.raises(ValueError, match="symlink"):
        emit_layer3_overlay(r3, _minimal_profile(), img, PROFILE_SCHEMA)
    assert victim_yaml.read_text(encoding="utf-8") == "secret: keep\n"

    # 4. Custom agent-authored Dockerfile.customer must survive re-emit (M2).
    r4 = tmp_path / "r-custom-df"
    (r4 / ".factory").mkdir(parents=True)
    (r4 / "README.md").write_text("# R4\n", encoding="utf-8")
    custom_df = f"FROM {img}\nRUN echo custom-nx\nUSER scion\n"
    (r4 / ".factory" / "Dockerfile.customer").write_text(custom_df, encoding="utf-8")
    out = emit_layer3_overlay(r4, _minimal_profile(), img, PROFILE_SCHEMA)
    assert ".factory/Dockerfile.customer" in out["preserved_custom_dockerfiles"]
    assert (r4 / ".factory" / "Dockerfile.customer").read_text(encoding="utf-8") == custom_df


def test_h5_l1_l4_l5_rust_gradle_commands_slug_and_readiness(tmp_path: pathlib.Path) -> None:
    """Locks in H5 (Rust/Gradle exact test cmds), L1 (1-char slug), L4 (generic deploy_target), and L5."""
    rust_repo = tmp_path / "x"
    rust_repo.mkdir()
    (rust_repo / "Cargo.toml").write_text("[package]\nname = 'x'\n", encoding="utf-8")
    rust_scan = scan_repository_facts(rust_repo, GENERIC_TOOLCHAIN, pack="generic")
    assert rust_scan["commands"]["test"] == "cargo test"
    assert rust_scan["commands"]["lint"] == "cargo clippy -- -D warnings"
    rust_draft = build_draft_profile(rust_scan, pack="generic", track="complete")
    assert len(rust_draft["slug"]) >= 2 and _sanitize_slug("x") == "x-app"

    gradle_repo = tmp_path / "java-svc"
    gradle_repo.mkdir()
    (gradle_repo / "build.gradle.kts").write_text("plugins { java }\n", encoding="utf-8")
    gradle_scan = scan_repository_facts(gradle_repo, GENERIC_TOOLCHAIN, pack="generic")
    assert gradle_scan["commands"]["test"] == "./gradlew test"

    # Generic pack rejects ADK/CES deploy targets and requires commands.e2e on complete cloud-run.
    bad_prof = _minimal_profile(deploy_target="agent-engine")
    assert check_readiness(bad_prof, PROFILE_SCHEMA)["ready"] is False

    cloudrun_complete = _minimal_profile(deploy_target="cloud-run")
    cloudrun_complete.update({
        "track": "complete",
        "mission": "Serve billing HTTP APIs cleanly on Cloud Run.",
        "non_goals": ["No direct database schema drops."],
        "requirements": [{"id": "REQ-001", "summary": "Expose /healthz HTTP 200.", "acceptance_criteria": ["curl /healthz returns 200."]}],
        "invariants": ["Never expose stack traces to HTTP clients."],
        "evaluation_pyramid": {"l1_offline": "pytest -q", "l2_sandbox": "python3 /opt/generic-factory/generic_sandbox_gate.py --level 2"},
    })
    chk = check_readiness(cloudrun_complete, PROFILE_SCHEMA)
    assert chk["ready"] is False and any("commands.e2e" in msg for msg in chk["missing_or_weak"])


def test_m3_kp_check_blocks_empty_index_duplicates_word_boundary_and_orphan_reqs(tmp_path: pathlib.Path) -> None:
    """Locks in M3 hardened fail-closed kp-check rules."""
    repo = tmp_path / "kp-strict"
    (repo / ".factory" / "knowledge").mkdir(parents=True)
    (repo / ".factory" / "waves").mkdir(parents=True)
    (repo / "AGENTS.md").write_text("See .factory/knowledge-index.yaml\n", encoding="utf-8")
    (repo / ".factory" / "knowledge" / "requirements.md").write_text("### REQ-0010: Only ten\n", encoding="utf-8")
    (repo / ".factory" / "knowledge-index.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "sources": [],
            "knowledge_files": [".factory/knowledge/requirements.md"],
            "requirements": [{"id": "REQ-001", "summary": "One"}, "bad-string-entry"],
        }),
        encoding="utf-8",
    )
    (repo / ".factory" / "waves" / "wave-1.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "tasks": [
                {"id": "W1-01", "title": "First", "req_ids": ["REQ-404"], "size": "small"},
                {"id": "W1-01", "title": "Duplicate", "req_ids": [], "size": "small"},
            ],
        }),
        encoding="utf-8",
    )
    res = check_knowledge_plane(repo)
    assert res["ok"] is False
    joined = "\n".join(res["errors"])
    assert "missing canonical knowledge_files" in joined
    assert "Invalid requirement entry" in joined
    assert "REQ-001" in joined  # word-boundary prevents REQ-0010 false match
    assert "Duplicate task ID 'W1-01'" in joined
    assert "unknown requirement ID 'REQ-404'" in joined


def test_m4_m5_h6_generic_gate_env_allowlist_l2_fail_closed_and_janitor(tmp_path: pathlib.Path) -> None:
    """Locks in M4 (L1 env scrub), M5 (L2 fail-closed), and H6 (Cloud Run CI janitor)."""
    gate = _load_module("generic_sandbox_gate", REPO_ROOT / "packs/generic/scripts/generic_sandbox_gate.py")
    janitor = _load_module("generic_janitor", REPO_ROOT / "packs/generic/scripts/sandbox_janitor.py")

    env = gate.build_l1_offline_env(
        {
            "PATH": "/usr/bin",
            "GOOGLE_OAUTH_ACCESS_TOKEN": "dummy-oauth-token-fixture",
            "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE": "/tmp/tok",
            "GOOGLE_CLOUD_PROJECT": "secret-proj",
            "CLOUDSDK_CONFIG": "/home/user/.config/gcloud",
        },
        tmp_path / "empty-gcloud",
    )
    assert "GOOGLE_OAUTH_ACCESS_TOKEN" not in env
    assert "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE" not in env
    assert "GOOGLE_CLOUD_PROJECT" not in env
    assert env["GCE_METADATA_HOST"] == "127.0.0.1:1"
    assert env["CLOUDSDK_CONFIG"] == str(tmp_path / "empty-gcloud")

    repo = tmp_path / "l2-repo"
    (repo / ".factory").mkdir(parents=True)
    (repo / ".factory" / "factory-profile.yaml").write_text(
        yaml.safe_dump({"slug": "l2-repo", "deploy_target": "cloud-run", "commands": {"lint": "true", "test": "true", "e2e": ""}}),
        encoding="utf-8",
    )
    l2 = gate.run_generic_gate(repo, level=2)
    assert l2["ok"] is False and "commands.e2e is empty" in l2["error"]

    # Janitor selects ONLY expired CI services and preserves non-CI customer services.
    now = dt.datetime(2026, 11, 25, 20, 0, tzinfo=dt.timezone.utc)
    services = [
        {"metadata": {"name": "ci-pr-12-abc", "labels": {"factory_ci": "true"}, "creationTimestamp": "2026-11-25T14:00:00Z"}},
        {"metadata": {"name": "ci-pr-13-fresh", "labels": {"factory_ci": "true"}, "creationTimestamp": "2026-11-25T19:00:00Z"}},
        {"metadata": {"name": "prod-billing-api", "labels": {}, "creationTimestamp": "2026-10-01T00:00:00Z"}},
    ]
    expired = janitor.select_expired_ci_services(services, ttl_hours=4.0, now_utc=now)
    assert [e["name"] for e in expired] == ["ci-pr-12-abc"]


def test_h1_h2_h3_m7_stage03_contract_fail_closed_idempotency_and_core_version(tmp_path: pathlib.Path) -> None:
    """Locks in H1 (CLI contract flags), H2 (fail-closed list), H3 (v0.5.0 non-regression & disabled coord), and M7."""
    contract = json.loads(SCION_CONTRACT.read_text(encoding="utf-8"))
    allowed_start = set(contract["start_flags"]) | set(contract["global_flags"])
    allowed_list = set(contract["list_flags"]) | set(contract["global_flags"])

    kit_dir = tmp_path / "generic-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/generic", kit_dir)
    assert manifest["core_version"] == "0.6.0"

    lz = tmp_path / "lz.json"
    lz.write_text(
        json.dumps({
            "hub_project_id": {"value": "cust-hub"},
            "region": {"value": "us-central1"},
            "artifact_registry_url": {"value": "us-central1-docker.pkg.dev/cust-hub/factory-images"},
            "inference_project_id": {"value": "cust-inf"},
            "worker_sa_email": {"value": "worker@cust-inf.iam.gserviceaccount.com"},
        }),
        encoding="utf-8",
    )

    # M7: stage-release-kit.sh --dry-run uses _CORE_VERSION=0.6.0 from manifest.json.
    dry = subprocess.run(
        [str(kit_dir / "bootstrap" / "stage-release-kit.sh"), "--kit", str(kit_dir), "--landing-zone", str(lz), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry.returncode == 0, dry.stderr
    assert "_CORE_VERSION=0.6.0" in dry.stdout

    # Build strict stub scion that validates every start/list flag against the captured CLI contract!
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "scion.log"
    list_mode = tmp_path / "list_mode.txt"
    stub = bin_dir / "scion"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "{log_file}"
if [[ "$1" == "version" ]]; then echo "scion version v0.4.0-preview.3"; exit 0; fi
if [[ "$*" == *"--format json list"* ]]; then
  mode="$(cat "{list_mode}")"
  if [[ "$mode" == "fail" ]]; then exit 1; fi
  if [[ "$mode" == "banner" ]]; then echo "Banner line"; echo '[{{"name":"sw-coordinator"}}]'; exit 0; fi
  if [[ "$mode" == "other_proj" ]]; then echo '[{{"name":"sw-coordinator","projectSlug":"other-proj"}}]'; exit 0; fi
  echo "[]"
  exit 0
fi
if [[ "$*" == *"service-accounts list"* || "$*" == *"schedule list"* || "$*" == *"project skills list"* ]]; then echo "[]"; exit 0; fi
if [[ "$*" == *"service-accounts add"* ]]; then echo '{{"id":"sa-1"}}'; exit 0; fi
if [[ "$*" == *"service-accounts verify"* ]]; then echo '{{"verified":true}}'; exit 0; fi
if [[ "$*" == *"skills resolve"* || "$*" == *"templates pull"* ]]; then exit 1; fi
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    bootstrap = kit_dir / "bootstrap" / "bootstrap-hub-project.sh"
    real_img = "us-central1-docker.pkg.dev/cust-hub/factory-images/generic-runtime@sha256:" + ("f" * 64)

    def _run_apply(repo_dir: pathlib.Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        log_file.write_text("", encoding="utf-8")
        cmd = [
            str(bootstrap), "apply", "--kit", str(kit_dir), "--hub", "http://127.0.0.1:8080",
            "--project", "my-proj", "--landing-zone", str(lz), "--repo", str(repo_dir),
            "--backup-dir", str(tmp_path / f"bkp-{repo_dir.name}"), "--harness-image-antigravity", real_img,
            *(extra or []),
        ]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)

    # H3a: Legacy v0.5.0 repo (no coordinator-bootstrap-brief.md) must NOT auto-start coordinator.
    legacy = tmp_path / "legacy-v050"
    (legacy / ".factory").mkdir(parents=True)
    (legacy / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1", "pack": "generic", "pack_version": "0.6.0", "mode": "ci-only",
            "diversity_profile": "cross-model", "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
        }),
        encoding="utf-8",
    )
    list_mode.write_text("empty", encoding="utf-8")
    r_leg = _run_apply(legacy)
    assert r_leg.returncode == 0, r_leg.stderr
    assert "start " not in log_file.read_text(encoding="utf-8")

    # H3b: Disabled coordinator in roster must NOT start even when brief exists.
    dis = tmp_path / "disabled-coord"
    (dis / ".factory").mkdir(parents=True)
    (dis / ".factory" / "coordinator-bootstrap-brief.md").write_text("# Brief\n", encoding="utf-8")
    (dis / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1", "pack": "generic", "pack_version": "0.6.0", "mode": "ci-only",
            "diversity_profile": "cross-model", "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [], "roster": {"enabled_roles": ["developer"], "disabled_roles": ["coordinator"]},
        }),
        encoding="utf-8",
    )
    r_dis = _run_apply(dis)
    assert r_dis.returncode == 0, r_dis.stderr
    assert "coordinator role is disabled" in r_dis.stdout
    assert "start " not in log_file.read_text(encoding="utf-8")

    # H2a & H2b: scion list failure or banner non-JSON fails closed (skips start, no duplicate).
    v6 = tmp_path / "v060-repo"
    (v6 / ".factory").mkdir(parents=True)
    (v6 / ".factory" / "coordinator-bootstrap-brief.md").write_text("# Brief\n", encoding="utf-8")
    (v6 / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1", "pack": "generic", "pack_version": "0.6.0", "mode": "ci-only", "deploy_target": "none",
            "diversity_profile": "cross-model", "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [], "kaizen": {"enabled": True, "schedule_cron": "0 17 * * 5", "time_zone": "America/Sao_Paulo", "coordinator_agent": "sw-coordinator"},
        }),
        encoding="utf-8",
    )
    for bad_mode in ("fail", "banner"):
        list_mode.write_text(bad_mode, encoding="utf-8")
        res_bad = _run_apply(v6)
        assert res_bad.returncode == 0, res_bad.stderr
        assert "Skipping automatic coordinator start" in res_bad.stderr
        assert "start sw-coordinator" not in log_file.read_text(encoding="utf-8")

    # H2c + H1: same-name agent in OTHER project does NOT cause false skip, and every emitted flag is in Scion contract!
    list_mode.write_text("other_proj", encoding="utf-8")
    res_ok = _run_apply(v6)
    assert res_ok.returncode == 0, res_ok.stderr
    calls = log_file.read_text(encoding="utf-8").splitlines()
    start_lines = [ln for ln in calls if ln.startswith("start ")]
    list_lines = [ln for ln in calls if "--format json list" in ln]
    assert len(start_lines) == 1 and len(list_lines) == 1
    for tok in shlex.split(start_lines[0]):
        if tok.startswith("-"):
            assert tok in allowed_start, f"Unverified scion start flag: {tok}"
    for tok in shlex.split(list_lines[0]):
        if tok.startswith("-"):
            assert tok in allowed_list, f"Unverified scion list flag: {tok}"


def test_h7_m8_stage01_optional_sandbox_and_generic_custom_roles() -> None:
    """Locks in Stage 01 enable_sandbox_project=false support and narrow genericSandboxDeployer IAM."""
    vars_tf = (REPO_ROOT / "deploy/01-landing-zone/variables.tf").read_text(encoding="utf-8")
    gen_tf = (REPO_ROOT / "deploy/01-landing-zone/iam_generic.tf").read_text(encoding="utf-8")
    finops_tf = (REPO_ROOT / "deploy/01-landing-zone/finops.tf").read_text(encoding="utf-8")

    assert 'variable "enable_sandbox_project"' in vars_tf
    assert 'variable "enable_generic_sandbox_roles"' in vars_tf
    assert "staging_project_id = var.enable_sandbox_project ? var.sandbox_project_id : var.hub_project_id" in finops_tf
    assert 'role_id     = "genericSandboxDeployer"' in gen_tf
    assert '"aiplatform.reasoningEngines' not in gen_tf
    assert '"discoveryengine.' not in gen_tf
    assert '"ces.' not in gen_tf
    assert '".*"' not in gen_tf
