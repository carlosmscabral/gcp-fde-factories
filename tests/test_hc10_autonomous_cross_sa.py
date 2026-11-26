"""Regression tests locking HC-10 live empirical fixes (HC10-F6 through HC10-F10).

Covers Discovery Engine service identity materialization, DEVNULL stdin isolation
in adk_sandbox_gate.run_cli, numeric GCP project-number equivalence in Verdict
verification, regional VertexAiSessionService fallback plus explicit eval judge
model pinning, and Lite Single-VM scion-hub.internal Kaizen bridge allowlisting.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from unittest import mock

from packs.adk.scripts import adk_sandbox_gate
from scripts.lib.io_utils import sha256_tree
from scripts.lib.kaizen_sources import _is_safe_hub_url
from scripts.lib.verdict_checker import verify_verdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICT_SCHEMA = REPO_ROOT / "schemas/verdict.schema.json"


def test_hc10_f6_discoveryengine_service_identity_in_landing_zone() -> None:
    """Confirms Stage 01 IAM materializes the Discovery Engine service identity for ADK sandboxes."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    assert 'resource "google_project_service_identity" "sandbox_discoveryengine_agent"' in iam_tf
    assert 'service = "discoveryengine.googleapis.com"' in iam_tf


def test_hc10_f7_adk_sandbox_gate_detaches_stdin_devnull(tmp_path: pathlib.Path) -> None:
    """Confirms run_cli attaches stdin=DEVNULL so fresh-HOME ADK CLI prompts never hang."""
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    with mock.patch.object(adk_sandbox_gate.subprocess, "run", side_effect=fake_run):
        res = adk_sandbox_gate.run_cli(["echo", "ok"], {"PATH": "/usr/bin"}, tmp_path, timeout=30)

    assert res.returncode == 0
    assert captured.get("stdin") is subprocess.DEVNULL


def test_hc10_f8_verdict_checker_supports_numeric_project_number_and_workflow_wires_it(
    tmp_path: pathlib.Path,
) -> None:
    """Confirms Verdict verification accepts matching numeric GCP project numbers and rejects foreign ones."""
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    (evals_dir / "smoke.json").write_text('{"id":"c1"}\n', encoding="utf-8")
    commit = "a" * 40

    def write_verdict(re_resource: str, ge_resource: str | None = None) -> pathlib.Path:
        out = tmp_path / "verdict.json"
        out.write_text(
            json.dumps({
                "schema_version": "1",
                "pack": "adk",
                "pr_number": 1,
                "commit_sha": commit,
                "diversity_profile": "cross-model",
                "ephemeral_app_name": re_resource,
                "ge_agent_resource": ge_resource,
                "evaluation_run_ids": [],
                "expected_evaluator_sa": "hc10-eval@sbx-proj.iam.gserviceaccount.com",
                "evals_tree_sha256": sha256_tree(evals_dir),
                "gates_executed": ["l1:pytest", "l2:agent-engine-remote-smoke", "l2:adk-eval"],
                "gates_skipped": [],
                "not_verifiable_surfaces": [],
                "verdict": "live-gcp-verified",
                "created_at_utc": "2026-11-26T21:15:00Z",
            }),
            encoding="utf-8",
        )
        return out

    numeric_re = "projects/911134361387/locations/us-central1/reasoningEngines/5734475681752940544"
    id_re = "projects/sbx-proj/locations/us-central1/reasoningEngines/5734475681752940544"
    numeric_ge = (
        "projects/911134361387/locations/global/collections/default_collection/"
        "engines/ge-app/assistants/default_assistant/agents/ag-1"
    )

    def fake_live_get(url: str, token: str, proj: str) -> tuple[int, dict[str, str]]:
        if "reasoningEngines" in url:
            return 200, {"name": numeric_re, "displayName": f"[CI] PR-1-{commit[:7]} Starter"}
        return 200, {"name": numeric_ge, "displayName": f"[CI] PR-1-{commit[:7]} Starter"}

    # Numeric ReasoningEngine and GE resource pass when sandbox_project_number matches.
    errs_num = verify_verdict(
        write_verdict(numeric_re, numeric_ge),
        VERDICT_SCHEMA,
        commit,
        evals_dir,
        sandbox_project="sbx-proj",
        sandbox_project_number="911134361387",
        expected_evaluator_sa="hc10-eval@sbx-proj.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=fake_live_get,
        require_live=True,
    )
    assert errs_num == []

    # String project ID in verdict also passes when GCP GET returns the canonical numeric project number.
    errs_mixed = verify_verdict(
        write_verdict(id_re, numeric_ge),
        VERDICT_SCHEMA,
        commit,
        evals_dir,
        sandbox_project="sbx-proj",
        sandbox_project_number="911134361387",
        expected_evaluator_sa="hc10-eval@sbx-proj.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=fake_live_get,
        require_live=True,
    )
    assert errs_mixed == []

    # Foreign numeric project number fails closed.
    foreign_re = "projects/999999999999/locations/us-central1/reasoningEngines/5734475681752940544"
    errs_foreign = verify_verdict(
        write_verdict(foreign_re),
        VERDICT_SCHEMA,
        commit,
        evals_dir,
        sandbox_project="sbx-proj",
        sandbox_project_number="911134361387",
        expected_evaluator_sa="hc10-eval@sbx-proj.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=fake_live_get,
        require_live=True,
    )
    assert errs_foreign != []

    wf = (REPO_ROOT / "packs/adk/repo-scaffold/.github/workflows/adk-verdict-gate.yml").read_text(encoding="utf-8")
    assert "SANDBOX_PROJECT_NUMBER" in wf
    assert "--sandbox-project-number" in wf


def test_hc10_f9_services_rejects_global_location_and_eval_config_pins_judge_model(monkeypatch) -> None:
    """Confirms ADK session location helper never returns global and eval_config pins a real global judge model."""
    services_src = (REPO_ROOT / "packs/adk/repo-scaffold/app/app_utils/services.py").read_text(encoding="utf-8")
    assert "def _resolve_agent_engine_location()" in services_src
    assert 'val.lower() != "global"' in services_src

    # Execute the extracted location fallback logic directly without requiring google-adk installed.
    namespace: dict[str, object] = {"os": __import__("os")}
    fn_start = services_src.index("def _resolve_agent_engine_location()")
    fn_end = services_src.index("@functools.cache", fn_start)
    exec(services_src[fn_start:fn_end], namespace)
    resolve_loc = namespace["_resolve_agent_engine_location"]

    for key in (
        "ADK_AGENT_ENGINE_REGION",
        "AGENT_ENGINE_REGION",
        "CLOUD_RUN_REGION",
        "GOOGLE_CLOUD_REGION",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    assert resolve_loc() == "us-central1"

    monkeypatch.setenv("ADK_AGENT_ENGINE_REGION", "europe-west4")
    assert resolve_loc() == "europe-west4"

    eval_cfg = json.loads((REPO_ROOT / "packs/adk/repo-scaffold/evals/eval_config.json").read_text(encoding="utf-8"))
    match_v2 = eval_cfg["criteria"]["final_response_match_v2"]
    assert isinstance(match_v2, dict)
    assert match_v2["judgeModelOptions"]["judgeModel"] == "gemini-4-neon"

    deployer_delta = (REPO_ROOT / "packs/adk/templates/adk-deployer/delta.md").read_text(encoding="utf-8")
    assert "ADK_AGENT_ENGINE_REGION" in deployer_delta
    assert "GOOGLE_CLOUD_LOCATION=global" in deployer_delta


def test_hc10_f10_kaizen_allows_lite_vm_bridge_host_and_blocks_external_http() -> None:
    """Confirms Kaizen Hub URL guard allows Lite VM bridge scion-hub.internal and rejects arbitrary HTTP hosts."""
    assert _is_safe_hub_url("https://hub.example.com/api/v1/metrics")
    assert _is_safe_hub_url("http://127.0.0.1:8080/api/v1/metrics")
    assert _is_safe_hub_url("http://localhost:8080/api/v1/metrics")
    assert _is_safe_hub_url("http://scion-hub.internal:8080/api/v1/metrics")
    assert not _is_safe_hub_url("http://10.44.0.2:8080/api/v1/metrics")
    assert not _is_safe_hub_url("http://evil.example.com/api/v1/metrics")


def test_adk_sandbox_runtime_role_grants_sessions_without_engine_or_iam_writes() -> None:
    """Confirms adkSandboxRuntime grants VertexAiSessionService and telemetry rights with zero engine or IAM mutations."""
    iam_tf = (REPO_ROOT / "deploy/01-landing-zone/iam.tf").read_text(encoding="utf-8")
    start = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_runtime"')
    end = iam_tf.index('resource "google_project_iam_member" "adk_runtime_sandbox_sessions"', start)
    role_block = iam_tf[start:end]

    for required in (
        "aiplatform.sessions.create",
        "aiplatform.sessions.get",
        "aiplatform.sessions.list",
        "aiplatform.sessionEvents.append",
        "aiplatform.sessionEvents.list",
        "logging.logEntries.create",
    ):
        assert f'"{required}"' in role_block

    for forbidden in (
        "aiplatform.reasoningEngines.create",
        "aiplatform.reasoningEngines.delete",
        "resourcemanager.projects.setIamPolicy",
        "iam.roles.update",
        "iam.serviceAccounts.getAccessToken",
    ):
        assert forbidden not in role_block

    dep_start = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_deployer"')
    dep_end = iam_tf.index('resource "google_project_iam_custom_role" "adk_sandbox_evaluator"', dep_start)
    assert '"logging.logEntries.list"' in iam_tf[dep_start:dep_end]


def test_remote_agent_engine_smoke_catches_session_403_and_empty_stream() -> None:
    """Confirms remote Agent Engine smoke fails closed on session errors or empty SSE streams and passes on real output."""
    from packs.adk.scripts.lib.agent_engine_smoke import run_remote_agent_engine_smoke

    re_name = "projects/427709713022/locations/us-central1/reasoningEngines/1948074295041196032"

    def ok_post(url: str, headers: dict[str, str], body: dict[str, object]) -> tuple[int, str]:
        if url.endswith(":query"):
            return 200, json.dumps({"output": {"id": "sess-123"}})
        return 200, json.dumps({"content": {"parts": [{"text": "Status is operational."}]}})

    ok, info = run_remote_agent_engine_smoke(re_name, "tok", "sbx-proj", post_fn=ok_post)
    assert ok is True
    assert info == "sess-123"

    def session_403_post(url: str, headers: dict[str, str], body: dict[str, object]) -> tuple[int, str]:
        return 403, '{"error":{"code":403,"message":"Permission aiplatform.sessions.create denied"}}'

    ok_403, err_403 = run_remote_agent_engine_smoke(re_name, "tok", "sbx-proj", post_fn=session_403_post)
    assert ok_403 is False
    assert "403" in err_403

    def empty_stream_post(url: str, headers: dict[str, str], body: dict[str, object]) -> tuple[int, str]:
        if url.endswith(":query"):
            return 200, json.dumps({"output": {"id": "sess-456"}})
        return 200, ""

    ok_empty, err_empty = run_remote_agent_engine_smoke(re_name, "tok", "sbx-proj", post_fn=empty_stream_post)
    assert ok_empty is False
    assert "empty" in err_empty.lower()
