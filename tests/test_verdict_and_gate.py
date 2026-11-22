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


def _make_verdict(tmp_path: pathlib.Path, evals_dir: pathlib.Path, overrides: dict) -> pathlib.Path:
    """Writes a baseline Verdict JSON for unit tests."""
    base = {
        "schema_version": "1",
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
    out = tmp_path / "verdict.json"
    out.write_text(json.dumps(base), encoding="utf-8")
    return out


def test_forged_verdict_rejected_when_ces_run_missing_or_failed(tmp_path: pathlib.Path) -> None:
    """Negative test: forged live-gcp-verified Verdict fails when CES API reports missing or failed run."""
    evals = tmp_path / "evals"
    evals.mkdir()
    (evals / "g.yaml").write_text("name: g1\n", encoding="utf-8")
    verdict_path = _make_verdict(tmp_path, evals, {})

    def fake_fetch_pass(url: str, token: str, proj: str) -> tuple[int, dict]:
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

    def fake_fetch_forged(url: str, token: str, proj: str) -> tuple[int, dict]:
        return 200, {"evaluationRuns": []}

    assert (
        verify_verdict(verdict_path, VERDICT_SCHEMA, "a" * 40, evals, "sbx", "gecx-eval@sbx.iam.gserviceaccount.com", "tok", fake_fetch_pass)
        == []
    )
    errs = verify_verdict(verdict_path, VERDICT_SCHEMA, "a" * 40, evals, "sbx", "gecx-eval@sbx.iam.gserviceaccount.com", "tok", fake_fetch_forged)
    assert any("does not exist in CES Sandbox" in e for e in errs)


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
