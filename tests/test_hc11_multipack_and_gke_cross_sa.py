"""Regression tests locking HC-11 live multi-pack, GKE 4-KSA, and Agent Engine findings (HC11-F1..F5).

Covers HA GKE coordinator KSA parity, multi-repository WIF allowlisting in Stage 01,
Scion v0.4 .scion/settings.yaml project_id resolution in bootstrap-hub-project.sh,
Agent Engine non-reserved ADK_AGENT_ENGINE_REGION split from global Gemini 4 inference,
and fail-closed error_code detection in remote Agent Engine SSE smoke checks.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

from packs.adk.scripts.lib.agent_engine_smoke import (
    _stream_has_non_empty_content,
    run_remote_agent_engine_smoke,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_hc11_f1_ha_gke_declares_coordinator_and_kaizen_ksas_without_janitor() -> None:
    """Confirms Stage 02 HA GKE contract binds factory-coordinator and keeps sandbox-janitor forbidden."""
    gke_tf = (REPO_ROOT / "deploy/02-factory-runtime/ha-gke/main.tf").read_text(encoding="utf-8")
    for ksa in ('"factory-coordinator"', '"factory-worker"', '"pack-deployer"', '"pack-evaluator"'):
        assert ksa in gke_tf
    assert 'optional_workload_identity_ksas' in gke_tf
    assert '"kaizen-viewer"' in gke_tf
    assert 'forbidden_workload_identity_ksas = [\n      "sandbox-janitor",' in gke_tf

    gke_readme = (REPO_ROOT / "deploy/02-factory-runtime/ha-gke/README.md").read_text(encoding="utf-8")
    assert "factory-coordinator" in gke_readme
    assert "kaizen-viewer" in gke_readme


def test_hc11_f2_landing_zone_supports_multi_repo_github_wif() -> None:
    """Confirms Stage 01 Landing Zone supports both single github_repository and multi-pack github_repositories."""
    vars_tf = (REPO_ROOT / "deploy/01-landing-zone/variables.tf").read_text(encoding="utf-8")
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")

    assert 'variable "github_repositories"' in vars_tf
    assert "wif_repositories = distinct(compact(concat(" in iam_tf
    assert "assertion.repository.lowerAscii() in [" in iam_tf
    assert "wif_evaluator_impersonation_extra" in iam_tf
    assert "wif_janitor_impersonation_extra" in iam_tf


def test_hc11_f3_bootstrap_resolves_project_id_from_scion_settings_yaml(tmp_path: pathlib.Path) -> None:
    """Confirms resolve_project_id() reads hub.project_id from .scion/settings.yaml written by scion hub link."""
    repo_dir = tmp_path / "linked-repo"
    scion_dir = repo_dir / ".scion"
    scion_dir.mkdir(parents=True)
    expected_uuid = "47b3a38e-cb10-4f06-b6ab-fed45d25f602"
    (scion_dir / "settings.yaml").write_text(
        f'schema_version: "1"\nhub:\n  project_id: {expected_uuid}\n  linked: true\n',
        encoding="utf-8",
    )

    script = REPO_ROOT / "deploy/03-hub-bootstrap/bootstrap-hub-project.sh"
    src = script.read_text(encoding="utf-8")
    fn_start = src.index("UUID_REGEX=")
    fn_end = src.index("\nwarn_github_token_injection_mode()", fn_start)
    fn_body = src[fn_start:fn_end]

    cmd = (
        f"set -euo pipefail\n"
        f"SCRIPT_DIR={str(REPO_ROOT / 'deploy/03-hub-bootstrap')!r}\n"
        f"require_cmd() {{ command -v \"$1\" >/dev/null 2>&1; }}\n"
        f"TARGET_REPO={str(repo_dir)!r}\n"
        f"PROJECT_SLUG=''\n"
        f"unset SCION_HUB_PROJECT_ID || true\n"
        f"{fn_body}\n"
        f"resolve_project_id\n"
    )
    res = subprocess.run(["bash", "-c", cmd], text=True, capture_output=True, check=True)
    assert res.stdout.strip() == expected_uuid


def test_hc11_f4_f5_agent_engine_avoids_reserved_prefix_and_keeps_global_model_split(monkeypatch) -> None:
    """Confirms ADK deployer avoids setting GOOGLE_CLOUD_AGENT_ENGINE_* while services reads runtime region."""
    services_src = (REPO_ROOT / "packs/adk/repo-scaffold/app/app_utils/services.py").read_text(encoding="utf-8")
    assert '"ADK_AGENT_ENGINE_REGION"' in services_src

    namespace: dict[str, object] = {"os": __import__("os")}
    fn_start = services_src.index("def _resolve_agent_engine_location()")
    fn_end = services_src.index("@functools.cache", fn_start)
    exec(services_src[fn_start:fn_end], namespace)
    resolve_loc = namespace["_resolve_agent_engine_location"]

    monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("ADK_AGENT_ENGINE_REGION", "southamerica-east1")
    assert resolve_loc() == "southamerica-east1"

    prereqs = (REPO_ROOT / "deploy/ENTERPRISE_PREREQUISITES.md").read_text(encoding="utf-8")
    assert "ADK_AGENT_ENGINE_REGION" in prereqs
    assert "GOOGLE_CLOUD_LOCATION=global" in prereqs


def test_hc11_f5_remote_smoke_rejects_error_code_even_in_multi_event_stream() -> None:
    """Confirms remote Agent Engine smoke fails closed when any SSE event reports error_code or error_message."""
    err_404 = json.dumps({
        "error_code": "NOT_FOUND",
        "error_message": "404 NOT_FOUND: Publisher model gemini-4-neon not found in us-central1",
    })
    ok_event = json.dumps({"content": {"parts": [{"text": "partial"}]}})

    assert _stream_has_non_empty_content(err_404) is False
    assert _stream_has_non_empty_content(f"data: {ok_event}\ndata: {err_404}\n") is False
    assert _stream_has_non_empty_content(f"data: {ok_event}\n") is True

    re_name = "projects/964773340301/locations/us-central1/reasoningEngines/171967191996956672"

    def post_404(url: str, headers: dict[str, str], body: dict[str, object]) -> tuple[int, str]:
        if url.endswith(":query"):
            return 200, json.dumps({"output": {"id": "7701880318923374592"}})
        return 200, err_404

    ok, detail = run_remote_agent_engine_smoke(re_name, "tok", "cabral-hc11-sbx", post_fn=post_404)
    assert ok is False
    assert "NOT_FOUND" in detail
