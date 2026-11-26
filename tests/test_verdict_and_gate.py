"""Tests for Contract 4 (Sandbox REST gate + Janitor) and Contract 5 (Anti-forgery Verdict)."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from packs.gecx.scripts.gecx_sandbox_gate import evaluate_rest_runs
from packs.gecx.scripts.sandbox_janitor import select_expired_ci_apps
from scripts.lib.io_utils import sha256_tree
from scripts.lib.verdict_checker import verify_verdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICT_SCHEMA = REPO_ROOT / "schemas/verdict.schema.json"


def _make_verdict(tmp_path: pathlib.Path, evals_dir: pathlib.Path, overrides: dict, name: str = "verdict.json") -> pathlib.Path:
    """Writes a baseline Verdict JSON for unit tests."""
    base = {
        "schema_version": "1",
        "pack": "gecx",
        "pr_number": 42,
        "commit_sha": "a" * 40,
        "diversity_profile": "cross-vendor",
        "ephemeral_app_name": "projects/sbx/locations/us/apps/app-123",
        "evaluation_run_ids": ["projects/sbx/locations/us/apps/app-123/evaluationRuns/run-1"],
        "expected_evaluator_sa": "gecx-eval@sbx.iam.gserviceaccount.com",
        "evals_tree_sha256": sha256_tree(evals_dir),
        "gates_executed": ["l1:cxas-lint", "l2:evaluator-run"],
        "gates_skipped": [],
        "not_verifiable_surfaces": [],
        "verdict": "live-gcp-verified",
        "created_at_utc": "2026-11-22T20:00:00Z",
    }
    base.update(overrides)
    out = tmp_path / name
    out.write_text(json.dumps(base), encoding="utf-8")
    return out


def test_forged_verdict_rejected_when_ces_run_missing_or_failed(tmp_path: pathlib.Path) -> None:
    """Negative test: forged live-gcp-verified Verdict fails when CES API reports missing or failed run."""
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "g.yaml").write_text("name: g1\n", encoding="utf-8")
    verdict_path = _make_verdict(tmp_path, evals, {})

    def fake_fetch_pass(url: str, token: str, proj: str) -> tuple[int, dict]:
        if url.endswith("/evaluationRuns"):
            return 200, {
                "evaluationRuns": [
                    {
                        "name": "projects/sbx/locations/us/apps/app-123/evaluationRuns/run-1",
                        "state": "SUCCEEDED",
                        "progress": {"totalCount": 2, "failedCount": 0, "completedCount": 2},
                        "initiatedBy": "gecx-eval@sbx.iam.gserviceaccount.com",
                    }
                ]
            }
        return 200, {"name": "projects/sbx/locations/us/apps/app-123", "displayName": f"[CI] PR-42-{'a' * 7} DemoApp"}

    def fake_fetch_cross_pr_reuse(url: str, token: str, proj: str) -> tuple[int, dict]:
        if url.endswith("/evaluationRuns"):
            return fake_fetch_pass(url, token, proj)
        return 200, {"name": "projects/sbx/locations/us/apps/app-123", "displayName": "[CI] PR-99-fffffff OtherApp"}

    def fake_fetch_forged(url: str, token: str, proj: str) -> tuple[int, dict]:
        if url.endswith("/evaluationRuns"):
            return 200, {"evaluationRuns": []}
        return 200, {"name": "projects/sbx/locations/us/apps/app-123", "displayName": f"[CI] PR-42-{'a' * 7} DemoApp"}

    assert (
        verify_verdict(verdict_path, VERDICT_SCHEMA, "a" * 40, evals, "sbx", "gecx-eval@sbx.iam.gserviceaccount.com", "tok", fake_fetch_pass)
        == []
    )
    errs = verify_verdict(verdict_path, VERDICT_SCHEMA, "a" * 40, evals, "sbx", "gecx-eval@sbx.iam.gserviceaccount.com", "tok", fake_fetch_forged)
    assert any("does not exist in CES Sandbox" in e for e in errs)
    # Negative test (B-01): reusing another PR's passing CES app must fail PR/SHA binding check.
    errs_reuse = verify_verdict(
        verdict_path, VERDICT_SCHEMA, "a" * 40, evals, "sbx", "gecx-eval@sbx.iam.gserviceaccount.com", "tok", fake_fetch_cross_pr_reuse
    )
    assert any("not bound to PR-42" in e for e in errs_reuse)


def test_gecx_cross_pack_downgrade_and_adk_forgery_vectors_blocked(tmp_path: pathlib.Path) -> None:
    """Negative tests (ADK-04/ADK-06/ADK-07): blocks GECX run-less downgrade, ADK missing eval/SA/PR binding, and unauthorized surfaces."""
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "g.yaml").write_text("name: g1\n", encoding="utf-8")

    # 1. GECX verdict claiming live-gcp-verified with empty evaluation_run_ids MUST fail schema validation (ADK-06).
    gecx_downgrade = _make_verdict(tmp_path, evals, {"pack": "gecx", "evaluation_run_ids": []}, "gecx-down.json")
    errs = verify_verdict(gecx_downgrade, VERDICT_SCHEMA, "a" * 40, evals)
    assert errs != []

    # 2a. ADK live-gcp-verified without l2:adk-eval MUST fail schema validation (ADK-04).
    adk_no_eval = _make_verdict(
        tmp_path,
        evals,
        {
            "pack": "adk",
            "ephemeral_app_name": "projects/sbx/locations/us-central1/reasoningEngines/re-1",
            "evaluation_run_ids": [],
            "gates_executed": ["l1:ge-export-bundle"],
        },
        "adk-noeval.json",
    )
    errs_no_eval = verify_verdict(adk_no_eval, VERDICT_SCHEMA, "a" * 40, evals)
    assert errs_no_eval != []

    # 2b. ADK live-gcp-verified with wrong project or unbound displayName MUST fail live API check (ADK-04).
    adk_wrong_proj = _make_verdict(
        tmp_path,
        evals,
        {
            "pack": "adk",
            "ephemeral_app_name": "projects/other-proj/locations/us-central1/reasoningEngines/re-1",
            "evaluation_run_ids": [],
            "expected_evaluator_sa": "adk-eval@sbx.iam.gserviceaccount.com",
            "gates_executed": ["l1:ge-export-bundle", "l2:agent-engine-remote-smoke", "l2:adk-eval"],
        },
        "adk-wrong-proj.json",
    )
    errs_proj = verify_verdict(
        adk_wrong_proj,
        VERDICT_SCHEMA,
        "a" * 40,
        evals,
        sandbox_project="sbx",
        expected_evaluator_sa="adk-eval@sbx.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=lambda url, t, p: (200, {"name": "projects/other-proj/locations/us-central1/reasoningEngines/re-1", "displayName": "unrelated"}),
    )
    assert any("sandbox_project" in e for e in errs_proj)

    adk_unbound = _make_verdict(
        tmp_path,
        evals,
        {
            "pack": "adk",
            "ephemeral_app_name": "projects/sbx/locations/us-central1/reasoningEngines/re-1",
            "evaluation_run_ids": [],
            "expected_evaluator_sa": "adk-eval@sbx.iam.gserviceaccount.com",
            "gates_executed": ["l1:ge-export-bundle", "l2:agent-engine-remote-smoke", "l2:adk-eval"],
        },
        "adk-unbound.json",
    )
    errs_unbound = verify_verdict(
        adk_unbound,
        VERDICT_SCHEMA,
        "a" * 40,
        evals,
        sandbox_project="sbx",
        expected_evaluator_sa="adk-eval@sbx.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=lambda url, t, p: (200, {"name": "projects/sbx/locations/us-central1/reasoningEngines/re-1", "displayName": "unrelated"}),
    )
    assert any("not bound to PR-42" in e for e in errs_unbound)

    # 3. Unauthorized not_verifiable_surfaces and require_live downgrade MUST fail (ADK-07).
    unauth = _make_verdict(
        tmp_path,
        evals,
        {
            "verdict": "not-verifiable-in-sandbox",
            "ephemeral_app_name": None,
            "evaluation_run_ids": [],
            "not_verifiable_surfaces": ["made-up-excuse"],
        },
        "unauth.json",
    )
    errs_surf = verify_verdict(
        unauth, VERDICT_SCHEMA, "a" * 40, evals,
        allowed_surfaces={"sip-trunk-routing"}, require_live=False,
    )
    assert any("Unauthorized not_verifiable_surfaces" in e for e in errs_surf)
    errs_req_live = verify_verdict(
        unauth, VERDICT_SCHEMA, "a" * 40, evals,
        allowed_surfaces={"sip-trunk-routing"}, require_live=True,
    )
    assert any("live-gcp-verified" in e for e in errs_req_live)


def test_evals_tree_tampering_detected(tmp_path: pathlib.Path) -> None:
    """Negative test: changing evals/ after Verdict generation breaks evals_tree_sha256 verification."""
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "g.yaml").write_text("name: original\n", encoding="utf-8")
    verdict_path = _make_verdict(tmp_path, evals, {"verdict": "unit-test-verified", "ephemeral_app_name": None, "evaluation_run_ids": []})
    (evals / "g.yaml").write_text("name: tampered\n", encoding="utf-8")

    errs = verify_verdict(verdict_path, VERDICT_SCHEMA, "a" * 40, evals)
    assert any("evals/ tree SHA-256 mismatch" in e for e in errs)


def test_rest_gate_fails_closed_on_zero_runs_and_janitor_selects_only_expired_ci() -> None:
    """Confirms REST gate rejects empty runs and Janitor deletes only [CI] apps older than 4h."""
    ok, _, reasons = evaluate_rest_runs([])
    assert not ok
    assert any("0 runs" in r for r in reasons)

    now = dt.datetime(2026, 11, 22, 20, 0, tzinfo=dt.timezone.utc)
    apps = [
        {"name": "apps/old-ci", "displayName": "[CI] PR-1", "createTime": "2026-11-22T15:00:00Z"},
        {"name": "apps/fresh-ci", "displayName": "[CI] PR-2", "createTime": "2026-11-22T18:30:00Z"},
        {"name": "apps/human-app", "displayName": "DevApp", "createTime": "2026-11-20T10:00:00Z"},
    ]
    expired = select_expired_ci_apps(apps, now, max_age_hours=4.0)
    assert [a["name"] for a in expired] == ["apps/old-ci"]


def test_adk_ge_only_cross_pr_reuse_is_blocked(tmp_path: pathlib.Path) -> None:
    """Negative test (B-01): ADK GE-only Verdict cannot reuse another PR's [CI] Discovery Engine agent."""
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "c.json").write_text("{}\n", encoding="utf-8")
    ge_res = "projects/sbx/locations/global/collections/default_collection/engines/e1/assistants/default_assistant/agents/a1"
    vp = _make_verdict(
        tmp_path,
        evals,
        {
            "pack": "adk",
            "ephemeral_app_name": None,
            "ge_agent_resource": ge_res,
            "evaluation_run_ids": [],
            "expected_evaluator_sa": "adk-eval@sbx.iam.gserviceaccount.com",
            "gates_executed": ["l1:ge-export-bundle", "l2:adk-eval"],
        },
        "ge-only.json",
    )
    errs = verify_verdict(
        vp,
        VERDICT_SCHEMA,
        "a" * 40,
        evals,
        sandbox_project="sbx",
        expected_evaluator_sa="adk-eval@sbx.iam.gserviceaccount.com",
        access_token="tok",
        fetch_fn=lambda url, t, p: (200, {"name": ge_res, "displayName": "[CI] PR-99-bbbbbbb StaleAgent"}),
    )
    assert any("not bound to [CI], PR-42" in e for e in errs)
