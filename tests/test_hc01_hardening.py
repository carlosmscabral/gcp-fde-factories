"""Regression tests locking in all HC-2026-11-24-01 live Argolis E2E findings.

Verifies cross-project Stage 01 IAM boundaries, Stage 02 VM and GKE runtime contracts,
ADK scaffold defaults, Kaizen GraphQL query limits, Hillclimbing ledger sync,
and ASD-STE100 punctuation rules across formal governance docs.
"""
from __future__ import annotations

import pathlib
import re

from scripts.lib.hillclimbing_renderer import CORE_GATE_ORDER, load_ledger, render_dashboard_html

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _hcl_without_comments(path: pathlib.Path) -> str:
    """Strips comment-only lines from a Terraform file for structural assertions."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_stage01_cross_project_iam_and_apis_hc01_hardening() -> None:
    """Locks in F3, F17, F26, F27, F29, F32, and cross-project Hub/Inf/Sbx bindings."""
    apis_tf = _hcl_without_comments(REPO_ROOT / "deploy/01-landing-zone/apis.tf")
    finops_tf = _hcl_without_comments(REPO_ROOT / "deploy/01-landing-zone/finops.tf")
    iam_tf = _hcl_without_comments(REPO_ROOT / "deploy/01-landing-zone/iam.tf")

    assert '"policytroubleshooter.googleapis.com"' in apis_tf
    assert '"container.googleapis.com"' in apis_tf
    assert 'resource "google_project_service_identity" "ces_service_agent"' in finops_tf
    assert 'resource "google_storage_bucket_iam_member" "builder_staging_rw"' in finops_tf

    # F27: worker, deployer, and eval must never receive broad roles/aiplatform.user.
    assert "roles/aiplatform.user" not in iam_tf
    assert 'role_id     = "vertexInferencePredict"' in iam_tf
    for res_name in (
        "worker_vertex_predict",
        "deployer_inference_vertex_predict",
        "evaluator_inference_vertex_predict",
        "worker_service_usage",
        "deployer_inference_service_usage",
        "evaluator_inference_service_usage",
        "deployer_ar_reader",
        "sandbox_cloudrun_ar_reader",
        "sandbox_aiplatform_ar_reader",
        "sandbox_agent_engine_re_ar_reader",
        "deployer_builder_act_as",
        "deployer_worker_act_as",
        "deployer_hub_cloudbuild_editor",
        "deployer_hub_service_usage",
    ):
        assert f'"{res_name}"' in iam_tf, f"Missing HC-01 IAM resource {res_name}"

    # INV-04: janitor must never be granted Hub token minting.
    sa_iam_blocks = re.findall(r'resource "google_service_account_iam_member" "[^"]+" \{[^}]+\}', iam_tf)
    mint_blocks = [b for b in sa_iam_blocks if "serviceAccountTokenCreator" in b]
    assert mint_blocks
    assert all("sandbox_janitor" not in b for b in mint_blocks)


def test_stage02_vm_and_gke_runtime_contracts_hc01() -> None:
    """Locks in F1, F6, F17b, F18, F19, F20, F22, and F25 in Stage 02 templates."""
    cloud_init = (REPO_ROOT / "deploy/02-factory-runtime/lite-vm/cloud-init.tftpl").read_text(encoding="utf-8")
    vm_vars = _hcl_without_comments(REPO_ROOT / "deploy/02-factory-runtime/lite-vm/variables.tf")
    assert "--host 0.0.0.0" in cloud_init
    assert "http://scion-hub.internal:8080" in cloud_init
    assert "docker-credential-gcloud" in cloud_init
    assert "${gcp_iam_deny_unknown_policy}" in cloud_init
    assert 'default     = "fail-open"' in vm_vars

    ha_gke = _hcl_without_comments(REPO_ROOT / "deploy/02-factory-runtime/ha-gke/main.tf")
    assert "//deploy/terraform?ref=" not in ha_gke
    assert "deploy/helm/scion-hub" in ha_gke
    assert "deploy/terraform/configurations/hub-gke" in ha_gke
    assert "standard-rwx" in ha_gke
    assert "in_cluster_hub_tls_required = true" in ha_gke
    assert "pvc-or-cloudsql-required" in ha_gke
    assert "sandbox-janitor" in ha_gke


def test_adk_scaffold_defaults_and_kaizen_graphql_limit() -> None:
    """Locks in F16, F28, F30, and F31 across packs and Kaizen collector."""
    cfg = (REPO_ROOT / "packs/adk/repo-scaffold/agent/config.py").read_text(encoding="utf-8")
    assert '"gemini-4-neon"' in cfg
    assert "gemini-4-neon-high" not in cfg

    gcloudignore = (REPO_ROOT / "packs/adk/repo-scaffold/.gcloudignore").read_text(encoding="utf-8")
    assert ".agents/" in gcloudignore
    assert ".git/" in gcloudignore

    for pack in ("adk", "gecx"):
        gi = (REPO_ROOT / f"packs/{pack}/repo-scaffold/.gitignore").read_text(encoding="utf-8")
        assert ".scion/agents/" in gi

    kaizen_src = (REPO_ROOT / "scripts/lib/kaizen_repo_sources.py").read_text(encoding="utf-8")
    m = re.search(r'"--limit",\s*"(\d+)"', kaizen_src)
    assert m, "gh pr list must set an explicit --limit"
    assert int(m.group(1)) <= 30, f"gh pr list --limit {m.group(1)} risks GitHub 500k GraphQL node cap"


def test_hillclimbing_ledger_dashboard_sync_and_asd_ste100_docs() -> None:
    """Confirms ledger schema, zero-drift HTML sync, and zero semicolons in formal governance docs."""
    ledger_path = REPO_ROOT / "docs/hillclimbing-runs.jsonl"
    html_path = REPO_ROOT / "docs/hillclimbing-dashboard.html"
    runs, digest = load_ledger(ledger_path)

    baseline = runs[0]
    assert baseline["run_id"] == "HC-2026-11-24-01"
    assert baseline["core_v1"]["immutable"] is True
    assert list(baseline["core_v1"]["gates"].keys()) == CORE_GATE_ORDER

    ev = baseline["core_v1"]["evolution_metrics"]
    assert set(ev["manual_friction_count"].keys()) >= {"total", "showstoppers", "minor"}
    assert ev["manual_friction_count"]["total"] == (
        ev["manual_friction_count"]["showstoppers"] + ev["manual_friction_count"]["minor"]
    )
    assert ev["mock_to_reality_escape_rate"]["count"] == len(ev["mock_to_reality_escape_rate"]["finding_ids"])

    v2_gates = baseline["additive_gates"]["v2_cross_project"]["gates"]
    assert set(v2_gates.keys()) == {"M2.4", "M3.3", "M4.4", "M4.5", "M5.4"}

    # Zero-drift contract: committed HTML must match deterministic renderer byte-for-byte.
    assert html_path.is_file()
    assert html_path.read_text(encoding="utf-8") == render_dashboard_html(runs, digest)

    # ASD-STE100 Rule 8.1: zero semicolons in prose of Charter, Invariants, and ADRs.
    formal_docs = [
        REPO_ROOT / "docs/HILLCLIMBING_CHARTER.md",
        REPO_ROOT / "docs/INVARIANTS.md",
        *sorted((REPO_ROOT / "docs/adr").glob("ADR-*.md")),
    ]
    for doc in formal_docs:
        in_code = False
        for line_no, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if not in_code:
                assert ";" not in line, f"ASD-STE100 Rule 8.1 violation (semicolon) in {doc.name}:{line_no}"
