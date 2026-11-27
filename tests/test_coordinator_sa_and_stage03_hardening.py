"""Regression tests for live autonomous factory findings (HC-10 F1..F5).

Covers dedicated least-privilege Coordinator SA split (ADR-003), Coordinator duration/call
headroom, Stage 03 .scion/project-id fallback + AGY_ADC_AUTH, GITHUB_TOKEN always-mode check,
pack-scoped GitHub Actions variable hints, and multi-agent path matching in adk-verdict-gate.yml.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

import yaml

from scripts.lib.release_kit import build_release_kit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_parse_hub_project():
    """Dynamically imports deploy/03-hub-bootstrap/parse_hub_project.py."""
    spec = importlib.util.spec_from_file_location(
        "parse_hub_project_hc10",
        REPO_ROOT / "deploy/03-hub-bootstrap/parse_hub_project.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parse_hub_project_hc10"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_coordinator_sa_split_preserves_least_privilege_and_blocks_worker_escalation() -> None:
    """Confirms dedicated coordinator SA holds actAs only (never TokenCreator, never janitor) and worker holds zero actAs."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    code_only = "\n".join(line for line in iam_tf.splitlines() if not line.lstrip().startswith("#"))
    outputs_tf = (REPO_ROOT / "deploy/01-landing-zone/outputs.tf").read_text(encoding="utf-8")

    # Dedicated coordinator SA declared, minted by Hub, exported in outputs, and included in operator actAs map.
    assert 'resource "google_service_account" "coordinator"' in code_only
    assert 'account_id   = "${var.name_prefix}-coordinator"' in code_only
    assert 'resource "google_service_account_iam_member" "hub_mint_coordinator"' in code_only
    assert 'coordinator = google_service_account.coordinator.name' in code_only
    assert 'output "coordinator_sa_email"' in outputs_tf

    # Coordinator gets predict-only inference and actAs on worker, deployer, evaluator, kaizen_viewer — never janitor.
    assert 'resource "google_project_iam_member" "coordinator_vertex_predict"' in code_only
    for expected in (
        "coordinator_act_as_worker",
        "coordinator_act_as_deployer",
        "coordinator_act_as_evaluator",
        "coordinator_act_as_kaizen",
    ):
        assert f'resource "google_service_account_iam_member" "{expected}"' in code_only

    sa_blocks = re.findall(r'resource "google_service_account_iam_member" "[^"]+" \{[^}]+\}', code_only)
    coord_member_blocks = [
        blk for blk in sa_blocks
        if "google_service_account.coordinator.email" in blk and "hub_mint_coordinator" not in blk
    ]
    assert len(coord_member_blocks) == 4
    for blk in coord_member_blocks:
        assert 'role               = "roles/iam.serviceAccountUser"' in blk
        assert "serviceAccountTokenCreator" not in blk
        assert "sandbox_janitor" not in blk

    # Leaf workers must hold zero actAs grants on any other SA (ADR-003 boundary intact).
    worker_member_blocks = [
        blk for blk in sa_blocks
        if "member" in blk and "google_service_account.worker.email" in blk.split("member", 1)[1]
    ]
    assert worker_member_blocks == []


def test_release_kit_grants_extended_limits_only_to_coordinator(tmp_path: pathlib.Path) -> None:
    """Confirms Release Kit sets 0s wall-clock and 400/800 token caps on coordinator templates while leaf workers inherit Hub defaults."""
    kit_dir = tmp_path / "adk-kit"
    build_release_kit(REPO_ROOT, REPO_ROOT / "packs/adk", kit_dir)

    coord_yaml = yaml.safe_load((kit_dir / "templates/adk-coordinator/scion-agent.yaml").read_text(encoding="utf-8"))
    dev_yaml = yaml.safe_load((kit_dir / "templates/adk-developer/scion-agent.yaml").read_text(encoding="utf-8"))

    # "0s" satisfies Scion agent-v1.schema.json regex ^[0-9]+(s|m|h)$, blocks Hub 2h fallback, and disables wall-clock kill.
    assert coord_yaml["max_duration"] == "0s"
    assert re.fullmatch(r"[0-9]+(s|m|h)", coord_yaml["max_duration"])
    assert coord_yaml["max_turns"] == 400
    assert coord_yaml["max_model_calls"] == 800
    assert "SA slot: coordinator" in coord_yaml["description"]

    assert "max_duration" not in dev_yaml
    assert "max_turns" not in dev_yaml
    assert "max_model_calls" not in dev_yaml


def test_parse_hub_project_sets_agy_adc_auth_for_antigravity(tmp_path: pathlib.Path) -> None:
    """Confirms render_harness_config injects AGY_ADC_AUTH=true alongside Vertex AI project vars for antigravity."""
    mod = _load_parse_hub_project()
    src = REPO_ROOT / "core-gcp-fde/harness-configs/antigravity-vertex.yaml"
    dst = tmp_path / "out/config.yaml"
    mod.render_harness_config(
        src,
        dst,
        inference_project="demo-inf-proj",
        gemini_location="global",
        claude_region="global",
        image_override="us-central1-docker.pkg.dev/demo-hub/factory-images/adk-antigravity-runtime@sha256:" + ("a" * 64),
    )
    rendered = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert rendered["env"]["AGY_ADC_AUTH"] == "true"
    assert rendered["env"]["GOOGLE_CLOUD_PROJECT"] == "demo-inf-proj"
    assert rendered["env"]["GOOGLE_CLOUD_QUOTA_PROJECT"] == "demo-inf-proj"


def test_stage03_bootstrap_resolves_dot_scion_project_id_and_hardening_helpers() -> None:
    """Confirms Stage 03 reads .scion/project-id, registers coordinator SA, checks GITHUB_TOKEN, and prints CI vars."""
    script_path = REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh"
    text = script_path.read_text(encoding="utf-8")

    # Syntax check via bash -n.
    res = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr

    assert ".scion/project-id" in text
    assert ".coordinator_sa_email.value" in text
    assert 'register_and_verify_sa "$coord_sa" "$inf_p" "factory-coordinator"' in text
    assert 'ensure_coordinator_started "$pack_prefix" "$default_harness" "$repo_cfg" "${coord_sa:-$worker_sa}"' in text
    assert "AGY_ADC_AUTH=true" in text
    assert 'scion hub experiments enable lifecycle.idle_suspend --hub "$HUB_URL"' in text
    assert "warn_github_token_injection_mode" in text
    assert "print_github_ci_variables" in text
    assert "RUNTIME_IMAGE_DIGEST" in text


def test_adk_verdict_gate_matches_both_root_and_monorepo_subagent_paths() -> None:
    """Confirms adk-verdict-gate.yml protects evals/ and triggers REQUIRE_LIVE for both root and agents/<slug>/ layouts."""
    wf = (REPO_ROOT / "packs/adk/repo-scaffold/.github/workflows/adk-verdict-gate.yml").read_text(encoding="utf-8")
    assert "(^|.*/)evals/" in wf
    assert "git diff --no-renames --name-only" in wf
    assert "grep -Ev '^(README\\.md|docs/.*|.*\\.md|\\.factory/.*)$'" in wf

    eval_pat = re.compile(r"(^|.*/)evals/")
    live_pat = re.compile(r"(^|.*/)(app/|agent/|Dockerfile$)")

    assert eval_pat.search("evals/synthetic/smoke.evalset.json")
    assert eval_pat.search("agents/ciudadano-documentos/evals/synthetic/smoke.evalset.json")
    assert live_pat.search("app/agent.py")
    assert live_pat.search("Dockerfile")
    assert live_pat.search("agents/ciudadano-documentos/app/agent.py")
    assert live_pat.search("agents/ciudadano-documentos/Dockerfile")
    assert not live_pat.search("README.md")
