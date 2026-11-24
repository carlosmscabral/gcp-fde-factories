"""Tests for packs/adk (v0.1.0): budget, Dockerfile scaffold, GE App dual export, gate, and dual janitor."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import pytest

from canaries.adk.check_ge_contract import check_ge_export_contract
from packs.adk.scripts.lib.ge_payload import (
    build_agent_card,
    build_ge_agents_url,
    build_ge_registration_payload,
    delete_ge_agent,
    export_ge_bundle,
    patch_ge_agent,
    register_ge_agent,
    validate_ge_manifest,
)
from packs.adk.scripts.sandbox_janitor import run_janitor, select_expired_ci_resources
from scripts.lib.budget_engine import check_context_budget
from scripts.lib.io_utils import sha256_tree
from scripts.lib.schema_validator import validate_yaml_file
from scripts.lib.verdict_checker import verify_verdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GE_SCHEMA = REPO_ROOT / "schemas/ge-export.schema.json"
VERDICT_SCHEMA = REPO_ROOT / "schemas/verdict.schema.json"


def test_adk_pack_budget_schemas_dockerfile_and_scaffold_parity() -> None:
    """Confirms packs/adk passes schemas, context budget, canary, Dockerfile-first scaffold, and parity."""
    assert validate_yaml_file(REPO_ROOT / "packs/adk/pack.yaml", REPO_ROOT / "schemas/pack.schema.json") == []
    assert validate_yaml_file(REPO_ROOT / "packs/adk/compat.yaml", REPO_ROOT / "schemas/compat.schema.json") == []
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
    assert (scaffold / "Dockerfile").is_file()
    assert "adk api_server" in (scaffold / "Dockerfile").read_text(encoding="utf-8")
    agents = (scaffold / "AGENTS.md").read_bytes()
    assert (scaffold / "CLAUDE.md").read_bytes() == agents
    assert (scaffold / "GEMINI.md").read_bytes() == agents


def test_ge_export_supports_agent_engine_a2a_patch_and_rejects_bad_inputs(tmp_path: pathlib.Path) -> None:
    """Confirms GE export emits valid payloads (zero toolSettings), supports PATCH, and rejects invalid inputs."""
    ae_spec = json.loads((REPO_ROOT / "packs/adk/repo-scaffold/ge_manifest.json").read_text(encoding="utf-8"))
    assert validate_ge_manifest(ae_spec, GE_SCHEMA) == []
    ae_payload = build_ge_registration_payload(ae_spec)
    assert "adkAgentDefinition" in ae_payload
    assert "toolSettings" not in ae_payload["adkAgentDefinition"]
    assert "a2aAgentDefinition" not in ae_payload

    ae_bundle = export_ge_bundle(ae_spec, tmp_path / "ae-out", GE_SCHEMA)
    assert ae_bundle["export_mode"] == "agent_engine"
    assert (tmp_path / "ae-out" / "ge_registration_payload.json").exists()

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
            "skills": [
                {"id": "orders", "name": "Order Lookup", "description": "Fetches order status.", "tags": ["orders"]}
            ],
        },
        "agent_authorization": "projects/demo-ge-sandbox/locations/eu/authorizations/a2a-oauth",
    }
    assert validate_ge_manifest(a2a_spec, GE_SCHEMA) == []
    assert build_ge_agents_url(a2a_spec["gemini_enterprise"]).startswith("https://eu-discoveryengine.googleapis.com/v1alpha/")
    card = build_agent_card(a2a_spec)
    assert card["protocolVersion"] == "0.3.0" and card["skills"][0]["tags"] == ["orders"]
    a2a_payload = build_ge_registration_payload(a2a_spec)
    assert a2a_payload["authorizationConfig"]["agentAuthorization"] == a2a_spec["agent_authorization"]
    assert "toolAuthorizations" not in a2a_payload["authorizationConfig"]

    # Negative test (ADK-09): A2A skill without tags fails validation.
    no_tags = json.loads(json.dumps(a2a_spec))
    del no_tags["a2a"]["skills"][0]["tags"]
    assert validate_ge_manifest(no_tags, GE_SCHEMA) != []

    # Negative test (ADK-10): location/endpoint_location mismatch fails validation.
    bad_loc = json.loads(json.dumps(a2a_spec))
    bad_loc["gemini_enterprise"]["endpoint_location"] = "us"
    assert validate_ge_manifest(bad_loc, GE_SCHEMA) != []

    # Verify POST, PATCH, DELETE happy paths and negative cross-project DELETE refusal (ADK-14).
    seen_calls: list[tuple[str, str]] = []

    def fake_http(method: str, url: str, headers: dict, body: dict | None) -> tuple[int, dict]:
        seen_calls.append((method, url))
        return 200, {"name": "projects/demo-ge-sandbox/locations/eu/collections/default_collection/engines/ge-app-eu/assistants/default_assistant/agents/ag-99"}

    st, body = register_ge_agent(a2a_spec, "tok-adk", "demo-ge-sandbox", http_fn=fake_http)
    assert st == 200
    p_st, _ = patch_ge_agent(body["name"], a2a_spec, "tok-adk", "demo-ge-sandbox", http_fn=fake_http)
    assert p_st == 200
    assert "authorizationConfig" in seen_calls[-1][1]  # B-15: updateMask must include authorizationConfig
    d_st, _ = delete_ge_agent(body["name"], "eu", "tok-adk", "demo-ge-sandbox", http_fn=fake_http)
    assert d_st == 200
    assert [m for m, _ in seen_calls] == ["POST", "PATCH", "DELETE"]

    with pytest.raises(ValueError, match="Refusing cross-project DELETE"):
        delete_ge_agent(
            "projects/other-prod/locations/eu/collections/default_collection/engines/e1/assistants/default_assistant/agents/a1",
            "eu",
            "tok-adk",
            "demo-ge-sandbox",
            http_fn=fake_http,
        )


def test_adk_sandbox_gate_level1_honesty_and_dual_janitor(tmp_path: pathlib.Path) -> None:
    """Confirms Level 1 emits static-check-only without tests, live Verdict enforces PR/SHA binding, and Janitor sweeps both."""
    repo = tmp_path / "adk-repo"
    repo.mkdir()
    (repo / "evals").mkdir()
    (repo / "evals" / "case.json").write_text('{"id":"c1"}\n', encoding="utf-8")
    (repo / "ge_manifest.json").write_text(
        (REPO_ROOT / "packs/adk/repo-scaffold/ge_manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "Dockerfile").write_text(
        (REPO_ROOT / "packs/adk/repo-scaffold/Dockerfile").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    verdict_out = tmp_path / "verdict.json"
    commit = "b" * 40
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "packs/adk/scripts/adk_sandbox_gate.py"),
            "--repo-dir", str(repo),
            "--pr-number", "12",
            "--commit-sha", commit,
            "--mode", "level1-only",
            "--verdict-out", str(verdict_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    vdata = json.loads(verdict_out.read_text(encoding="utf-8"))
    assert vdata["verdict"] == "static-check-only"
    assert "l1:dockerfile-contract" in vdata["gates_executed"]
    assert verify_verdict(verdict_out, VERDICT_SCHEMA, commit, repo / "evals") == []

    # Negative test: root-only Dockerfile missing CMD fails Level 1 closed.
    bad_df_repo = tmp_path / "bad-df-repo"
    bad_df_repo.mkdir()
    (bad_df_repo / "evals").mkdir()
    (bad_df_repo / "Dockerfile").write_text("FROM python:3.12-slim\nUSER root\n", encoding="utf-8")
    bad_res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "packs/adk/scripts/adk_sandbox_gate.py"),
            "--repo-dir", str(bad_df_repo),
            "--pr-number", "13",
            "--commit-sha", commit,
            "--mode", "level1-only",
            "--verdict-out", str(tmp_path / "bad-verdict.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_res.returncode == 1
    assert json.loads((tmp_path / "bad-verdict.json").read_text(encoding="utf-8"))["verdict"] == "verifier-failed"

    # Verify live ADK Verdict passes ONLY when ReasoningEngine, GE agent, l2:adk-eval, and PR/SHA displayName match.
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
            "gates_executed": ["l1:ge-export-bundle", "l2:adk-eval", "l2:ge-sandbox-register"],
            "gates_skipped": [],
            "not_verifiable_surfaces": [],
            "verdict": "live-gcp-verified",
            "created_at_utc": "2026-11-24T13:00:00Z",
        }),
        encoding="utf-8",
    )

    def fake_live_get(url: str, token: str, proj: str) -> tuple[int, dict]:
        if "reasoningEngines/re-123" in url:
            return 200, {"name": "projects/sbx/locations/us-central1/reasoningEngines/re-123", "displayName": f"[CI] PR-12 {commit[:7]}"}
        return 200, {"name": ge_res, "displayName": f"[CI] PR-12 {commit[:7]}"}

    assert verify_verdict(
        live_verdict, VERDICT_SCHEMA, commit, repo / "evals",
        sandbox_project="sbx", expected_evaluator_sa="adk-eval@sbx.iam.gserviceaccount.com",
        access_token="tok", fetch_fn=fake_live_get,
    ) == []

    # Verify Janitor sweeps BOTH ReasoningEngines (?force=true, paginated) AND GE agents, and fails on HTTP 500.
    now = dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.timezone.utc)
    resources = [
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/old", "displayName": "[CI] PR-1", "createTime": "2026-11-24T09:00:00Z"},
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/new", "displayName": "[CI] PR-2", "createTime": "2026-11-24T13:30:00Z"},
        {"name": "projects/sbx/locations/us-central1/reasoningEngines/human", "displayName": "Manual Agent", "createTime": "2026-11-20T09:00:00Z"},
    ]
    assert select_expired_ci_resources(resources, now, max_age_hours=4.0) == [
        "projects/sbx/locations/us-central1/reasoningEngines/old"
    ]

    deleted_urls: list[str] = []

    def fake_janitor_http(method: str, url: str, token: str, proj: str) -> tuple[int, dict]:
        if method == "GET" and "reasoningEngines" in url:
            if "pageToken=p2" in url:
                return 200, {"reasoningEngines": [{"name": "projects/sbx/locations/us-central1/reasoningEngines/old2", "displayName": "[CI] PR-2", "createTime": "2026-11-24T08:00:00Z"}]}
            return 200, {"reasoningEngines": [resources[0]], "nextPageToken": "p2"}
        if method == "GET" and "/agents" in url:
            return 200, {"agents": [{"name": ge_res, "displayName": "[CI] PR-1", "createTime": "2026-11-24T08:00:00Z"}]}
        if method == "DELETE":
            deleted_urls.append(url)
            if "old2" in url:
                return 500, {"error": "internal"}
            return 200, {}
        return 404, {}

    rc, summary = run_janitor(
        project="sbx",
        regions=["us-central1"],
        token="tok",
        ge_location="global",
        ge_app="eng-1",
        max_age_hours=4.0,
        apply=True,
        now_utc=now,
        rest_fn=fake_janitor_http,
    )
    assert rc == 1
    assert any("reasoningEngines/old?force=true" in u for u in deleted_urls)
    assert any(ge_res in u for u in deleted_urls)
    assert len(summary["failures"]) == 1


def test_adk_dockerfile_multistage_contract_and_offline_scaffold_smoke(tmp_path: pathlib.Path) -> None:
    """Negative tests (B-12/B-25/B-10): final-stage USER check, scaffold offline pytest, and janitor skip_resources."""
    from packs.adk.scripts.adk_sandbox_gate import validate_dockerfile_contract

    for bad_name, content in (
        ("root_group", "FROM python:3.12-slim\nUSER root:root\nCMD [\"adk\"]\n"),
        ("uid_zero", "FROM python:3.12-slim\nUSER 0:1000\nCMD [\"adk\"]\n"),
        ("var_user", "FROM python:3.12-slim\nUSER ${APP_USER}\nCMD [\"adk\"]\n"),
        ("multistage_missing_user", "FROM python:3.12 AS builder\nUSER scion\nFROM python:3.12-slim\nCMD [\"adk\"]\n"),
    ):
        df = tmp_path / f"Dockerfile.{bad_name}"
        df.write_text(content, encoding="utf-8")
        assert validate_dockerfile_contract(df) != [], f"{bad_name} should fail"

    # Scaffold offline smoke test must pass without google-adk installed (B-25).
    smoke = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_agent_smoke.py", "-q"],
        cwd=str(REPO_ROOT / "packs/adk/repo-scaffold"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr

    # Shared PATCH-reused GE agent with fresh updateTime or skip_resources must NOT be swept (B-10).
    now = dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.timezone.utc)
    ge_items = [
        {"name": "agents/reused-fresh", "displayName": "[CI] PR-5", "createTime": "2026-11-20T00:00:00Z", "updateTime": "2026-11-24T14:30:00Z"},
        {"name": "agents/pinned-skip", "displayName": "[CI] PR-4", "createTime": "2026-11-20T00:00:00Z"},
    ]
    assert select_expired_ci_resources(ge_items, now, max_age_hours=4.0, skip_resources={"agents/pinned-skip"}) == []
