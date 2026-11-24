"""Regression tests locking in all HC-2026-11-24-02 live 3-project Argolis findings.

Verifies HC02-F3 (APT timeouts), HC02-F4 (dedicated GKE node SA), HC02-F5 (headless
SCION_HUB_PROJECT_ID for service-accounts), HC02-F6 (WK-006 + SA OIDC project list),
HC02-F7 (vpc_name output + Filestore custom-VPC doc), HC02-F8 (GOOGLE_CLOUD_QUOTA_PROJECT),
HC02-F10 (same-project adk_runtime SA), HC02-F12 (discoveryengine.agents.manage),
HC02-F13 (numeric project-number validation in ge_payload and adk_sandbox_gate), and
HC02-F14 (regional Agent Engine session location guidance + ENTERPRISE_PREREQUISITES.md).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from packs.adk.scripts.adk_sandbox_gate import _validate_reasoning_engine_project
from packs.adk.scripts.lib.ge_payload import delete_ge_agent, patch_ge_agent


def _load_parse_hub_project() -> Any:
    """Loads deploy/03-hub-bootstrap/parse_hub_project.py dynamically for unit testing."""
    mod_path = REPO_ROOT / "deploy/03-hub-bootstrap/parse_hub_project.py"
    spec = importlib.util.spec_from_file_location("parse_hub_project", mod_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hc02_stage01_gke_node_adk_runtime_and_ge_manage_iam() -> None:
    """Locks in HC02-F4 (gke_node SA), HC02-F7 (vpc_name), HC02-F10 (adk_runtime SA), and HC02-F12 (agents.manage)."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    outputs_tf = (REPO_ROOT / "deploy/01-landing-zone/outputs.tf").read_text(encoding="utf-8")

    for res_name in (
        'resource "google_service_account" "gke_node"',
        'resource "google_project_iam_member" "gke_node_default"',
        'resource "google_project_iam_member" "gke_node_ar_reader"',
        'resource "google_service_account" "adk_runtime"',
        'resource "google_service_account_iam_member" "deployer_adk_runtime_act_as"',
        'resource "google_project_iam_member" "adk_runtime_inference_predict"',
        'resource "google_project_iam_member" "adk_runtime_hub_ar_reader"',
    ):
        assert res_name in iam_tf, f"Missing HC-02 IAM block: {res_name}"

    assert iam_tf.count('"discoveryengine.agents.manage"') == 2

    for out_name in ("vpc_name", "sandbox_project_number", "gke_node_sa_email", "adk_runtime_sa_email"):
        assert f'output "{out_name}"' in outputs_tf, f"Missing Stage 01 output: {out_name}"


def test_hc02_lite_vm_apt_timeouts_oidc_projects_and_wk006() -> None:
    """Locks in HC02-F3 (apt timeouts) and HC02-F6 (oidc_allowed_gcp_projects + WK-006)."""
    cloud_init = (REPO_ROOT / "deploy/02-factory-runtime/lite-vm/cloud-init.tftpl").read_text(encoding="utf-8")
    vm_vars = (REPO_ROOT / "deploy/02-factory-runtime/lite-vm/variables.tf").read_text(encoding="utf-8")
    vm_tf = (REPO_ROOT / "deploy/02-factory-runtime/lite-vm/vm.tf").read_text(encoding="utf-8")

    assert "99-scion-timeouts" in cloud_init
    assert 'Acquire::http::Timeout "30"' in cloud_init
    assert "allowed_gcp_projects" in cloud_init
    assert 'variable "oidc_allowed_gcp_projects"' in vm_vars
    assert "oidc_allowed_gcp_projects" in vm_tf

    wk = yaml.safe_load((REPO_ROOT / "WORKAROUNDS.yaml").read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in wk["workarounds"]}
    assert "WK-006" in ids


def test_hc02_cross_project_quota_project_and_headless_sa_bootstrap(tmp_path: pathlib.Path) -> None:
    """Locks in HC02-F5 (SCION_HUB_PROJECT_ID resolver) and HC02-F8 (GOOGLE_CLOUD_QUOTA_PROJECT injection)."""
    mod = _load_parse_hub_project()
    src = tmp_path / "antigravity.yaml"
    dst = tmp_path / "rendered.yaml"
    src.write_text(
        yaml.safe_dump({
            "harness": "antigravity",
            "image": "us-central1-docker.pkg.dev/demo-hub/images/antigravity@sha256:" + ("a" * 64),
            "auth_selected_type": "vertex-ai",
        }),
        encoding="utf-8",
    )
    mod.render_harness_config(src, dst, inference_project="demo-inf", gemini_location="global", claude_region="global")
    rendered = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert rendered["env"]["GOOGLE_CLOUD_PROJECT"] == "demo-inf"
    assert rendered["env"]["GOOGLE_CLOUD_QUOTA_PROJECT"] == "demo-inf"

    boot_sh = (REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh").read_text(encoding="utf-8")
    assert "resolve_project_id()" in boot_sh
    assert "GOOGLE_CLOUD_QUOTA_PROJECT=" in boot_sh


def test_hc02_f13_numeric_project_number_validation_still_blocks_cross_project() -> None:
    """Locks in HC02-F13: accepts real GCP numeric project numbers when matched, rejects mismatched projects."""
    numeric_re = "projects/812512235697/locations/us-central1/reasoningEngines/5444011097973587968"
    assert _validate_reasoning_engine_project(numeric_re, "demo-sbx", "812512235697") is None
    assert _validate_reasoning_engine_project(numeric_re, "demo-sbx", "999999999999") is not None
    assert _validate_reasoning_engine_project(numeric_re, "demo-sbx", "") is not None

    numeric_ge = (
        "projects/812512235697/locations/global/collections/default_collection/"
        "engines/sbx-ge-app/assistants/default_assistant/agents/12345"
    )
    spec = {
        "schema_version": "1",
        "export_mode": "agent_engine",
        "display_name": "Smoke Agent",
        "description": "Smoke description",
        "gemini_enterprise": {"project_id": "demo-sbx", "location": "global", "app_id": "sbx-ge-app"},
        "agent_engine": {"reasoning_engine_resource": numeric_re},
    }
    calls: list[tuple[str, str]] = []

    def fake_http(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        calls.append((method, url))
        return 200, {"name": numeric_ge}

    st_p, _ = patch_ge_agent(
        numeric_ge, spec, "tok", "demo-sbx", http_fn=fake_http, quota_project_number="812512235697"
    )
    assert st_p == 200
    st_d, _ = delete_ge_agent(
        numeric_ge, "global", "tok", "demo-sbx", http_fn=fake_http, quota_project_number="812512235697"
    )
    assert st_d == 200
    assert [m for m, _ in calls] == ["PATCH", "DELETE"]

    with pytest.raises(ValueError, match="Refusing cross-project PATCH"):
        patch_ge_agent(numeric_ge, spec, "tok", "demo-sbx", http_fn=fake_http, quota_project_number="111111111111")

    with pytest.raises(ValueError, match="Refusing cross-project DELETE"):
        delete_ge_agent(numeric_ge, "global", "tok", "demo-sbx", http_fn=fake_http, quota_project_number="111111111111")


def test_hc02_enterprise_prerequisites_and_adr013_ste100_clean() -> None:
    """Verifies ENTERPRISE_PREREQUISITES.md and ADR-013 exist and obey ASD-STE100 Rule 8.1 (zero semicolons)."""
    prereqs = REPO_ROOT / "deploy/ENTERPRISE_PREREQUISITES.md"
    adr13 = REPO_ROOT / "docs/adr/ADR-013-cross-project-adc-quota-and-sandbox-runtime-sa.md"
    assert prereqs.is_file()
    assert adr13.is_file()
    for doc in (prereqs, adr13):
        in_code = False
        for idx, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if not in_code:
                assert ";" not in line, f"ASD-STE100 Rule 8.1 violation in {doc.name}:{idx}"
