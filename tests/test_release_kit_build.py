"""Tests for offline Release Kit composition, safety guards, Vertex AI harnesses, and Stage 03 bootstrap."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess

import pytest
import yaml

from scripts.lib.lock_verifier import scan_for_floating_uris
from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

FORBIDDEN_TEMPLATE_KEYS = {
    "name",
    "model",
    "harness",
    "harness_config",
    "default_harness_config",
    "image",
    "resources",
    "volumes",
    "kubernetes",
    "hub",
    "telemetry",
    "persistence",
}


def _assert_templates_follow_scion_v04_rules(
    out_dir: pathlib.Path, prefix: str, expected_count: int
) -> set[str]:
    """Asserts every generated template obeys offline Scion v0.4 rules and prefix isolation."""
    assert scan_for_floating_uris(out_dir / "templates") == []
    tpl_dirs = sorted(p for p in (out_dir / "templates").iterdir() if p.is_dir())
    assert len(tpl_dirs) == expected_count

    for tdir in tpl_dirs:
        assert tdir.name.startswith(f"{prefix}-")
        assert not tdir.name.startswith(f"{prefix}-{prefix}-")
        cfg_file = tdir / "scion-agent.yaml"
        assert cfg_file.is_file() and not cfg_file.is_symlink()
        agent_cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        assert FORBIDDEN_TEMPLATE_KEYS.isdisjoint(agent_cfg.keys())
        assert agent_cfg["schema_version"] == "1"
        assert agent_cfg["description"]
        assert agent_cfg["agent_instructions"] == "agents.md"
        assert agent_cfg["system_prompt"] == "system-prompt.md"
        for sk_ref in agent_cfg.get("skills", []):
            assert sk_ref["uri"].startswith("skill://scion/global/")
        for content_file in (tdir / "agents.md", tdir / "system-prompt.md"):
            assert content_file.is_file() and not content_file.is_symlink()
            assert content_file.stat().st_size > 0
        agents_text = (tdir / "agents.md").read_text(encoding="utf-8")
        assert f"`{prefix}-*`" in agents_text

    return {d.name for d in tpl_dirs}


def test_release_kit_is_offline_prefix_isolated_and_composes_core_deltas(tmp_path: pathlib.Path) -> None:
    """Verifies packs/gecx Release Kit composes core+pack deltas, excludes build-only libs, and builds template-pack."""
    out_dir = tmp_path / "gecx-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/gecx", out_dir)

    assert manifest["pack"] == "gecx"
    assert manifest["pack_prefix"] == "gecx"
    assert manifest["external_uris_remaining"] == 0
    assert manifest["toolchain_manifest"] == "packs/gecx/toolchain-manifest.json"
    assert "gecx-runtime" in manifest["images"]
    assert set(manifest["harness_configs"]) == {"gecx-claude-vertex", "gecx-antigravity-vertex"}
    assert (out_dir / "scripts" / "verify-verdict.py").is_file()
    assert (out_dir / "deploy" / "01-landing-zone" / "iam.tf").is_file()
    assert (out_dir / "fde-skills" / "factory-onboard" / "SKILL.md").is_file()
    assert (out_dir / "repo-scaffold" / ".factory" / "hub-project.yaml").is_file()

    # Catalog-only scripts/lib modules must not be shipped inside customer Release Kits (C-19).
    assert not (out_dir / "scripts" / "lib" / "sanitizer.py").exists()
    assert not (out_dir / "scripts" / "lib" / "release_kit.py").exists()

    # Verify Vertex AI-first defaults using Scion generic tiers (zero hardcoded model versions in harness-configs).
    agy_hc = yaml.safe_load((out_dir / "harness-configs" / "gecx-antigravity-vertex" / "config.yaml").read_text(encoding="utf-8"))
    assert agy_hc["auth_selected_type"] == "vertex-ai"
    assert agy_hc["model"] == "extra-large"
    assert "model_aliases" not in agy_hc
    cld_hc = yaml.safe_load((out_dir / "harness-configs" / "gecx-claude-vertex" / "config.yaml").read_text(encoding="utf-8"))
    assert cld_hc["auth_selected_type"] == "vertex-ai"
    assert cld_hc["model"] == "large"
    assert "model_aliases" not in cld_hc
    assert cld_hc["env"]["CLOUD_ML_REGION"] == "global"
    assert "ANTHROPIC_MODEL" not in cld_hc["env"]

    tpl_names = _assert_templates_follow_scion_v04_rules(out_dir, "gecx", expected_count=16)
    assert "gecx-kaizen-analyst" in tpl_names

    # Verify core-gcp-fde/templates/kaizen-analyst/delta.md IS composed before pack delta (KZ-12).
    kz_agents = (out_dir / "templates" / "gecx-kaizen-analyst" / "agents.md").read_text(encoding="utf-8")
    assert "Core FDE Override Rules" in kz_agents
    assert "Pack Override Rules" in kz_agents
    assert "proposal_verifications" in kz_agents

    manifest_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest_disk["skills"]) == 11
    for sk in manifest_disk["skills"]:
        assert len(sk["tree_sha256"]) == 64

    # Verify packs/_template-pack builds cleanly too (C-15).
    tpl_kit = tmp_path / "template-kit"
    tpl_manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/_template-pack", tpl_kit)
    assert tpl_manifest["pack"] == "example-pack"
    assert (tpl_kit / "packs" / "_template-pack" / "Dockerfile").is_file()


def test_adk_release_kit_ships_18_skills_and_adk_runtime_compat(tmp_path: pathlib.Path) -> None:
    """Verifies packs/adk Release Kit builds 16 adk-* templates, 18 skills (incl. 7 agents-cli), and adk-runtime."""
    out_dir = tmp_path / "adk-kit"
    manifest = build_release_kit(REPO_ROOT, REPO_ROOT / "packs/adk", out_dir)

    assert manifest["pack"] == "adk"
    assert manifest["external_uris_remaining"] == 0
    assert "adk-runtime" in manifest["images"]
    assert "gecx-runtime" not in manifest["images"]
    assert set(manifest["harness_configs"]) == {"adk-claude-vertex", "adk-antigravity-vertex"}
    assert (out_dir / "packs" / "adk" / "scripts" / "ge_export.py").is_file()

    tpl_names = _assert_templates_follow_scion_v04_rules(out_dir, "adk", expected_count=16)
    assert {"adk-coordinator", "adk-deployer", "adk-eval-tester", "adk-kaizen-analyst"}.issubset(tpl_names)

    assert len(manifest["skills"]) == 18
    skill_names = {s["name"] for s in manifest["skills"]}
    assert {
        "google-agents-cli-workflow",
        "google-agents-cli-adk-code",
        "google-agents-cli-scaffold",
        "google-agents-cli-eval",
        "google-agents-cli-deploy",
        "google-agents-cli-publish",
        "google-agents-cli-observability",
    }.issubset(skill_names)


def test_release_kit_refuses_deleting_non_kit_directory(tmp_path: pathlib.Path) -> None:
    """Negative test (IB-16): build_release_kit refuses deleting an arbitrary non-empty folder."""
    victim = tmp_path / "precious-folder"
    victim.mkdir()
    (victim / "notes.txt").write_text("do not delete\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to delete non-empty directory"):
        build_release_kit(REPO_ROOT, REPO_ROOT / "packs/gecx", victim)
    assert (victim / "notes.txt").exists()


def _install_stub_scion(bin_dir: pathlib.Path, log_file: pathlib.Path) -> None:
    """Writes an executable stub scion CLI that records every invocation to log_file."""
    stub = bin_dir / "scion"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> "{log_file}"
if [[ "$1" == "version" ]]; then
  echo "scion version v0.4.0-preview.3"
  exit 0
fi
if [[ "$*" == *"service-accounts list"* || "$*" == *"schedule list"* || "$*" == *"project skills list"* ]]; then
  echo "[]"
  exit 0
fi
if [[ "$*" == *"service-accounts add"* ]]; then
  echo '{{"id":"sa-stub-1"}}'
  exit 0
fi
if [[ "$*" == *"service-accounts verify"* ]]; then
  echo '{{"verified":true}}'
  exit 0
fi
if [[ "$*" == *"skills resolve"* || "$*" == *"templates pull"* ]]; then
  exit 1
fi
exit 0
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


def test_bootstrap_schedules_weekly_kaizen_by_default_and_enforces_claude_model_garden(tmp_path: pathlib.Path) -> None:
    """Tests bootstrap-hub-project.sh end-to-end: placeholder image guard, global harness sync, Kaizen, and overlay checks."""
    kit_dir = tmp_path / "gecx-kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs/gecx", kit_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "scion.log"
    _install_stub_scion(bin_dir, log_file)

    lz = tmp_path / "lz.json"
    lz.write_text(
        json.dumps({
            "inference_project_id": {"value": "cust-inf-proj"},
            "sandbox_project_id": {"value": "cust-sbx-proj"},
            "worker_sa_email": {"value": "worker@cust-inf-proj.iam.gserviceaccount.com"},
            "sandbox_deployer_sa_email": {"value": "dep@cust-sbx-proj.iam.gserviceaccount.com"},
            "sandbox_evaluator_sa_email": {"value": "eval@cust-sbx-proj.iam.gserviceaccount.com"},
        }),
        encoding="utf-8",
    )

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = {**os.environ, "HOME": str(fake_home), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    bootstrap = kit_dir / "bootstrap" / "bootstrap-hub-project.sh"
    real_agy_img = "us-central1-docker.pkg.dev/cust-hub/factory-images/gecx-antigravity-runtime@sha256:" + ("a" * 64)
    real_cld_img = "us-central1-docker.pkg.dev/cust-hub/factory-images/gecx-claude-runtime@sha256:" + ("b" * 64)

    # 0. Negative test (C-02/D-01): apply WITHOUT staged real harness images MUST fail closed on placeholder REPLACE_HUB_PROJECT.
    placeholder_fail = subprocess.run(
        [str(bootstrap), "apply", "--kit", str(kit_dir), "--hub", "http://127.0.0.1:8080", "--landing-zone", str(lz), "--backup-dir", str(tmp_path / "bkp0")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert placeholder_fail.returncode != 0
    assert "placeholder image" in placeholder_fail.stderr

    # 1. Default apply with real harness image: schedules daily-kaizen, syncs global harness-config, sets max_model_calls.
    log_file.write_text("", encoding="utf-8")
    res = subprocess.run(
        [
            str(bootstrap), "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--landing-zone", str(lz),
            "--backup-dir", str(tmp_path / "bkp1"),
            "--harness-image-antigravity", real_agy_img,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    calls = log_file.read_text(encoding="utf-8")
    assert "schedule list --show recurring --hub" in calls
    assert "schedule create-recurring --name daily-kaizen --cron 0 0 * * * --time-zone America/Sao_Paulo --type message --agent coordinator --wake" in calls
    assert "default_agent_role" not in calls  # read-only in Scion v0.4 server-config API (dbUnwrittenLayer1Paths)
    assert "default_max_model_calls 150" in calls
    assert "default_harness_config gecx-antigravity-vertex" in calls
    assert "harness-config sync gecx-antigravity-vertex --global --hub" in calls
    assert "gecx-claude-vertex --global" not in calls
    staged_agy = yaml.safe_load((fake_home / ".scion" / "harness-configs" / "gecx-antigravity-vertex" / "config.yaml").read_text(encoding="utf-8"))
    assert staged_agy["image"] == real_agy_img
    assert not ({"schema_version", "name", "resources"} & set(staged_agy))

    # 2. Negative test: rollback on 0-template first-install backup must fail closed.
    rb = subprocess.run(
        [str(bootstrap), "rollback", "--kit", str(kit_dir), "--hub", "http://127.0.0.1:8080", "--backup-dir", str(tmp_path / "bkp1")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rb.returncode != 0
    assert "0 backed-up templates" in rb.stderr

    # 3. Negative test: cross-vendor repo with claude_model_garden_enabled=false must fail closed.
    bad_repo = tmp_path / "bad-repo"
    (bad_repo / ".factory").mkdir(parents=True)
    (bad_repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "gecx",
            "pack_version": "0.4.0",
            "mode": "sandbox-direct",
            "diversity_profile": "cross-vendor",
            "harnesses": {"default": "antigravity-vertex", "claude_model_garden_enabled": False},
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
        }),
        encoding="utf-8",
    )
    bad = subprocess.run(
        [str(bootstrap), "apply", "--kit", str(kit_dir), "--hub", "http://127.0.0.1:8080", "--repo", str(bad_repo)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "claude_model_garden_enabled is false" in bad.stderr

    # 4. Explicit opt-out kaizen.enabled=false skips schedule creation, and claude_model_garden_enabled=true syncs Claude globally.
    log_file.write_text("", encoding="utf-8")
    opt_repo = tmp_path / "opt-repo"
    (opt_repo / ".factory").mkdir(parents=True)
    (opt_repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "gecx",
            "pack_version": "0.4.0",
            "mode": "sandbox-direct",
            "diversity_profile": "cross-vendor",
            "harnesses": {
                "default": "antigravity-vertex",
                "claude_model_garden_enabled": True,
                "vertex_claude_region": "global",
            },
            "kaizen": {"enabled": False},
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [],
        }),
        encoding="utf-8",
    )
    res2 = subprocess.run(
        [
            str(bootstrap), "apply",
            "--kit", str(kit_dir),
            "--hub", "http://127.0.0.1:8080",
            "--landing-zone", str(lz),
            "--repo", str(opt_repo),
            "--backup-dir", str(tmp_path / "bkp2"),
            "--harness-image-antigravity", real_agy_img,
            "--harness-image-claude", real_cld_img,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res2.returncode == 0, res2.stderr
    calls2 = log_file.read_text(encoding="utf-8")
    assert "schedule create-recurring" not in calls2
    assert "harness-config sync gecx-claude-vertex --global --hub" in calls2

    # 5. Negative test (D-19): overlay-sync rejects overlay skill colliding with pack skill name.
    col_repo = tmp_path / "col-repo"
    (col_repo / ".factory").mkdir(parents=True)
    (col_repo / "skills" / "gcp-fde-guardrails").mkdir(parents=True)
    (col_repo / "skills" / "gcp-fde-guardrails" / "SKILL.md").write_text("# colliding\n", encoding="utf-8")
    (col_repo / ".factory" / "hub-project.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "pack": "gecx",
            "pack_version": "0.4.0",
            "mode": "sandbox-direct",
            "diversity_profile": "cross-model",
            "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
            "overlay_skills": [{"dir": "skills/gcp-fde-guardrails", "version": "1.0.0"}],
        }),
        encoding="utf-8",
    )
    col_res = subprocess.run(
        [str(bootstrap), "overlay-sync", "--kit", str(kit_dir), "--hub", "http://127.0.0.1:8080", "--repo", str(col_repo)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert col_res.returncode != 0
    assert "collides" in col_res.stderr
