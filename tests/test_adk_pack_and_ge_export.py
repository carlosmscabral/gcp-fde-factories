"""Tests for packs/adk (v0.1.0): context budget, scaffold parity, GE App dual export, gate, and janitor."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

from canaries.adk.check_ge_contract import check_ge_export_contract
from packs.adk.scripts.lib.ge_payload import (
    build_agent_card,
    build_ge_agents_url,
    build_ge_registration_payload,
    delete_ge_agent,
    export_ge_bundle,
    register_ge_agent,
    validate_ge_manifest,
)
from packs.adk.scripts.sandbox_janitor import select_expired_ci_resources
from scripts.lib.budget_engine import check_context_budget
from scripts.lib.io_utils import sha256_tree
from scripts.lib.schema_validator import validate_yaml_file
from scripts.lib.verdict_checker import verify_verdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GE_SCHEMA = REPO_ROOT / "schemas/ge-export.schema.json"
VERDICT_SCHEMA = REPO_ROOT / "schemas/verdict.schema.json"


def test_adk_pack_budget_schemas_and_scaffold_parity() -> None:
    """Confirms packs/adk passes schemas, context budget, canary contract, and scaffold parity."""
    assert validate_yaml_file(REPO_ROOT / "packs/adk/pack.yaml", REPO_ROOT / "schemas/pack.schema.json") == []
    assert (
        validate_yaml_file(
            REPO_ROOT / "packs/adk/repo-scaffold/.factory/hub-project.yaml",
            REPO_ROOT / "schemas/hub-project.schema.json",
        )
        == []
    )
    errs, report = check_context_budget(
        REPO_ROOT,
        REPO_ROOT / "packs/adk",
        REPO_ROOT / "packs/adk/repo-scaffold/.factory/hub-project.yaml",
    )
    assert errs == []
    assert {"adk-deployer", "adk-eval-tester", "kaizen-analyst"}.issubset(report["roles"].keys())
    assert check_ge_export_contract(REPO_ROOT / "canaries/adk/ge_export_contract.json") == []

    scaffold = REPO_ROOT / "packs/adk/repo-scaffold"
    agents = (scaffold / "AGENTS.md").read_bytes()
    assert (scaffold / "CLAUDE.md").read_bytes() == agents
    assert (scaffold / "GEMINI.md").read_bytes() == agents


def test_ge_export_supports_both_agent_engine_and_a2a_modes(tmp_path: pathlib.Path) -> None:
    """Confirms dual GE App export emits valid Discovery Engine payloads, AgentCard, and REST calls."""
    ae_spec = json.loads((REPO_ROOT / "packs/adk/repo-scaffold/ge_manifest.json").read_text(encoding="utf-8"))
    assert validate_ge_manifest(ae_spec, GE_SCHEMA) == []

    ae_url = build_ge_agents_url(ae_spec["gemini_enterprise"])
    assert ae_url.startswith("https://discoveryengine.googleapis.com/v1alpha/projects/")
    ae_payload = build_ge_registration_payload(ae_spec)
    assert "adkAgentDefinition" in ae_payload
    assert "provisionedReasoningEngine" in ae_payload["adkAgentDefinition"]
    assert "a2aAgentDefinition" not in ae_payload

    ae_bundle = export_ge_bundle(ae_spec, tmp_path / "ae-out", GE_SCHEMA)
    assert ae_bundle["export_mode"] == "agent_engine"
    assert (tmp_path / "ae-out" / "ge_registration_payload.json").exists()
    assert not (tmp_path / "ae-out" / "agent_card.json").exists()

    # Build a regional EU A2A manifest and verify a2aAgentDefinition + AgentCard export + toolAuthorizations.
    a2a_spec = {
        "schema_version": "1",
        "export_mode": "a2a",
        "display_name": "Order Support A2A Agent",
        "description": "Handles order inquiries via A2A protocol.",
        "gemini_enterprise": {
            "project_id": "demo-ge-sandbox",
            "location": "eu",
            "endpoint_location": "eu",
            "app_id": "ge-app-eu",
            "assistant_id": "default_assistant",
        },
        "a2a": {
            "url": "https://orders-agent.example.com/a2a",
            "protocol_version": "0.3.0",
            "version": "1.0.0",
            "streaming": True,
            "default_input_modes": ["text/plain"],
            "default_output_modes": ["text/plain"],
            "skills": [{"id": "orders", "name": "Order Lookup", "description": "Fetches order status."}],
        },
        "tool_authorizations": [
            "projects/demo-ge-sandbox/locations/eu/authorizations/erp-oauth"
        ],
    }
    assert validate_ge_manifest(a2a_spec, GE_SCHEMA) == []
    assert build_ge_agents_url(a2a_spec["gemini_enterprise"]).startswith("https://eu-discoveryengine.googleapis.com/v1alpha/")
    card = build_agent_card(a2a_spec)
    assert card["protocolVersion"] == "0.3.0"
    a2a_payload = build_ge_registration_payload(a2a_spec)
    assert "a2aAgentDefinition" in a2a_payload
    assert json.loads(a2a_payload["a2aAgentDefinition"]["jsonAgentCard"])["url"] == "https://orders-agent.example.com/a2a"
    assert a2a_payload["authorizationConfig"]["toolAuthorizations"] == a2a_spec["tool_authorizations"]

    a2a_bundle = export_ge_bundle(a2a_spec, tmp_path / "a2a-out", GE_SCHEMA)
    assert "agent_card.json" in a2a_bundle["files_sha256"]
    assert (tmp_path / "a2a-out" / "agent_card.json").exists()

    # Verify mocked register_ge_agent and delete_ge_agent send exact headers and endpoints.
    seen_calls: list[tuple[str, str]] = []

    def fake_http(method: str, url: str, headers: dict, body: dict | None) -> tuple[int, dict]:
        seen_calls.append((method, url))
        assert headers["Authorization"] == "Bearer tok-adk"
        assert headers["x-goog-user-project"] == "demo-ge-sandbox"
        return 200, {"name": "projects/demo-ge-sandbox/locations/eu/collections/default_collection/engines/ge-app-eu/assistants/default_assistant/agents/ag-99"}

    st, body = register_ge_agent(a2a_spec, "tok-adk", "demo-ge-sandbox", http_fn=fake_http)
    assert st == 200
    d_st, _ = delete_ge_agent(body["name"], "eu", "tok-adk", "demo-ge-sandbox", http_fn=fake_http)
    assert d_st == 200
    assert seen_calls[0][0] == "POST" and seen_calls[1][0] == "DELETE"


def test_adk_sandbox_gate_level1_verdict_and_janitor_filter(tmp_path: pathlib.Path) -> None:
    """Confirms adk_sandbox_gate Level 1 produces a schema-valid Verdict and Janitor filters [CI] resources."""
    repo = tmp_path / "adk-repo"
    repo.mkdir()
    (repo / "evals").mkdir()
    (repo / "evals" / "case.json").write_text('{"id":"c1"}\n', encoding="utf-8")
    (repo / "ge_manifest.json").write_text(
        (REPO_ROOT / "packs/adk/repo-scaffold/ge_manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    verdict_out = tmp_path / "verdict.json"
    commit = "b" * 40
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "packs/adk/scripts/adk_sandbox_gate.py"),
            "--repo-dir",
            str(repo),
            "--pr-number",
            "12",
            "--commit-sha",
            commit,
            "--mode",
            "level1-only",
            "--verdict-out",
            str(verdict_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert (repo / "dist" / "ge-export" / "ge_registration_payload.json").exists()
    assert verify_verdict(verdict_out, VERDICT_SCHEMA, commit, repo / "evals") == []

    # Verify Contract 5 anti-forgery check for ADK live-gcp-verified GE Sandbox resource.
    ge_res = "projects/sbx/locations/global/collections/default_collection/engines/eng-1/assistants/default_assistant/agents/ag-1"
    live_verdict = tmp_path / "live-verdict.json"
    live_verdict.write_text(
        json.dumps({
            "schema_version": "1",
            "pack": "adk",
            "pr_number": 12,
            "commit_sha": commit,
            "diversity_profile": "cross-vendor",
            "ephemeral_app_name": "projects/sbx/locations/us-central1/reasoningEngines/re-123",
            "ge_agent_resource": ge_res,
            "evaluation_run_ids": [],
            "expected_evaluator_sa": "adk-eval@sbx.iam.gserviceaccount.com",
            "evals_tree_sha256": sha256_tree(repo / "evals"),
            "gates_executed": ["l1:ge-export-bundle", "l2:ge-sandbox-register"],
            "gates_skipped": [],
            "not_verifiable_surfaces": [],
            "verdict": "live-gcp-verified",
            "created_at_utc": "2026-11-24T13:00:00Z",
        }),
        encoding="utf-8",
    )

    def fake_live_get(url: str, token: str, proj: str) -> tuple[int, dict]:
        if "reasoningEngines/re-123" in url:
            return 200, {"name": "projects/sbx/locations/us-central1/reasoningEngines/re-123"}
        return 200, {"name": ge_res}

    assert verify_verdict(live_verdict, VERDICT_SCHEMA, commit, repo / "evals", "sbx", "", "tok", fake_live_get) == []

    # Verify Janitor selects only [CI]-prefixed resources older than 4h.
    now = dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.timezone.utc)
    resources = [
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/old", "displayName": "[CI] PR-1", "createTime": "2026-11-24T09:00:00Z"},
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/new", "displayName": "[CI] PR-2", "createTime": "2026-11-24T13:30:00Z"},
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/human", "displayName": "Manual Agent", "createTime": "2026-11-20T09:00:00Z"},
    ]
    assert select_expired_ci_resources(resources, now, max_age_hours=4.0) == [
        "projects/sbx/locations/us-central1/reasoningEngines/old"
    ]
