"""Tests for the v0.3.0 0-token Kaizen collector, Scion v0.4.0-preview.3 CLI contract, and closed-loop verifier."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

import yaml

from scripts.lib.kaizen_collector import build_kaizen_snapshot, write_validated_snapshot
from scripts.lib.kaizen_verifier import verify_proposals

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT_SCHEMA = REPO_ROOT / "schemas/kaizen-snapshot.schema.json"
SCION_CONTRACT = REPO_ROOT / "canaries/scion/cli_contract.json"


def test_kaizen_collector_uses_verified_scion_flags_and_validates(tmp_path: pathlib.Path) -> None:
    """Confirms collector uses exact Scion v0.4.0-preview.3 CLI flags, clamps rates, and handles malformed inputs."""
    contract = json.loads(SCION_CONTRACT.read_text(encoding="utf-8"))
    repo = tmp_path / "repo"
    (repo / ".factory" / "verdicts").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[tool.poetry]\nname='demo'\n[tool.ruff]\n", encoding="utf-8")
    (repo / ".factory" / "verdicts" / "pr-7.json").write_text(
        json.dumps({"pr_number": 7, "commit_sha": "a" * 40, "verdict": "live-gcp-verified"}),
        encoding="utf-8",
    )
    (repo / ".factory" / "verdicts" / "pr-8.json").write_text(
        json.dumps({"pr_number": 8, "commit_sha": "b" * 40, "verdict": "injected-bad-level"}),
        encoding="utf-8",
    )

    scratch = tmp_path / "scratchpad"
    scratch.mkdir()
    (scratch / "broken-verdict.json").write_text("{not-json", encoding="utf-8")
    (scratch / "sandbox-ledger.jsonl").write_text('{"app":"a1"}\n{"app":"a2"}\n', encoding="utf-8")
    (scratch / "kaizen-events.jsonl").write_text('{"event":"retry_spike"}\n', encoding="utf-8")

    wk = tmp_path / "WORKAROUNDS.yaml"
    wk.write_text(
        yaml.safe_dump({
            "max_age_days": 90,
            "workarounds": [
                {"id": "WK-101", "component": "scion", "added_date": "2026-09-01", "expires_date": "2026-12-01"},
                {"id": "WK-102", "component": "adk", "added_date": "2026-11-01", "expires_date": "2027-02-01"},
            ],
        }),
        encoding="utf-8",
    )

    seen_cmds: list[list[str]] = []

    def fake_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict]:
        assert headers["X-Scion-Agent-Token"] == "tok-123"
        if "/projects/proj-1/metrics/summary" in url:
            return 200, {
                "totalTokens": 120000,
                "mostUsedTools": [
                    {"name": "run_command", "calls": 20, "error": 25},
                    {"name": "read_file", "calls": 40, "error": 0},
                ],
            }
        return 200, {"agentId": url.split("/")[-3], "tokens": 60000}

    def fake_run_cmd(cmd: list[str], cwd: pathlib.Path | None) -> tuple[int, str, str]:
        seen_cmds.append(cmd)
        if cmd[:4] == contract["commands"]["list_agents_json"][:4]:
            return 0, json.dumps([
                {"id": "ag-1", "name": "dev-1", "phase": "stopped", "exitReason": "limits_exceeded"},
                {"id": "ag-2", "name": "rev-1", "phase": "stalled", "activity": "offline"},
            ]), ""
        if cmd[:6] == contract["commands"]["list_artifacts_json"][:6]:
            return 0, json.dumps({"artifacts": [{"id": "a1"}, {"id": "a2"}]}), ""
        if cmd[:5] == contract["commands"]["list_decisions_json"][:5]:
            return 0, json.dumps([{"id": "d1"}]), ""
        if cmd[:2] == ["gh", "pr"]:
            return 0, json.dumps([
                {
                    "number": 7,
                    "title": "feat: add retries",
                    "body": "",
                    "createdAt": "2026-11-20T10:00:00Z",
                    "mergedAt": "2026-11-20T14:00:00Z",
                    "mergeCommit": {"oid": "a" * 40},
                    "reviews": [{"state": "CHANGES_REQUESTED"}, {"state": "APPROVED"}],
                }
            ]), ""
        if cmd[:2] == ["gh", "run"]:
            return 0, json.dumps([{"conclusion": "success"}, {"conclusion": "failure"}]), ""
        if cmd[:2] == ["gh", "issue"]:
            return 0, json.dumps([{"number": 99}]), ""
        return 1, "", "unexpected"

    snap = build_kaizen_snapshot(
        hub_url="http://127.0.0.1:8080",
        project_id="proj-1",
        agent_token="tok-123",
        repo_dir=repo,
        scratchpad_dir=scratch,
        workarounds_path=wk,
        toolchain_manifest=REPO_ROOT / "packs/gecx/toolchain-manifest.json",
        include_drift=True,
        enable_gcp_obs=False,
        today=dt.date(2026, 11, 24),
        http_get=fake_http_get,
        run_cmd=fake_run_cmd,
    )

    out_path = tmp_path / "out" / "kaizen-snapshot.json"
    assert write_validated_snapshot(snap, out_path, SNAPSHOT_SCHEMA) == []
    assert snap["sources_status"]["scion_control_plane"] == "ok"
    assert snap["sources_status"]["hub_metrics"] == "ok"
    assert snap["hub_metrics"]["tool_error_rates"][0]["error_rate"] == 1.0  # clamped <= 1.0
    assert snap["control_plane"]["limits_exceeded_agents"] == ["dev-1"]
    assert snap["scratchpad"]["verdict_counts"] == {"live-gcp-verified": 1, "invalid": 2}
    assert any("malformed verdict" in e for e in snap["source_errors"])
    assert any(c[:4] == contract["commands"]["list_agents_json"][:4] for c in seen_cmds)


def test_kaizen_enable_gcp_obs_without_payload_reports_error(tmp_path: pathlib.Path) -> None:
    """Negative test (KZ-14): --enable-gcp-obs without --gcp-obs-json reports status='error'."""
    snap = build_kaizen_snapshot(
        hub_url="",
        project_id="",
        agent_token="",
        repo_dir=None,
        scratchpad_dir=None,
        workarounds_path=None,
        toolchain_manifest=None,
        include_drift=False,
        enable_gcp_obs=True,
        gcp_obs_payload=None,
        today=dt.date(2026, 11, 24),
    )
    assert snap["sources_status"]["gcp_observability"] == "error"
    assert any("gcp_observability" in e for e in snap["source_errors"])


def test_kaizen_closed_loop_verifier_detects_pass_rollback_and_reward_hacking() -> None:
    """Tests closed-loop proposal verification: Kaizen-Ref auto-detect, verified_pass, rollback, and anti-reward-hacking."""
    prior_snap = {
        "github_ci": {"avg_review_rounds": 3.0, "avg_lead_time_hours": 10.0, "failed_ci_runs": 4},
        "scratchpad": {"verdict_counts": {"live-gcp-verified": 9, "unit-test-verified": 1}},
        "hub_metrics": {"tool_error_rates": [{"tool": "run_command", "calls": 20, "errors": 8, "error_rate": 0.40}]},
    }
    proposals = [
        {
            "proposal_id": "KZ-2026-11-24-01",
            "status": "proposed",
            "target_metric": "avg_review_rounds",
            "rollback_criterion": {
                "operator": "<",
                "target_value": 2.0,
                "window_merged_prs": 2,
            },
        },
        {
            "proposal_id": "KZ-2026-11-24-02",
            "status": "implemented",
            "implemented_pr_number": 50,
            "merge_commit_sha": "c" * 40,
            "merged_at_utc": "2026-11-20T12:00:00Z",
            "target_metric": "avg_lead_time_hours",
            "rollback_criterion": {
                "operator": "<=",
                "target_value": 2.0,
                "window_merged_prs": 2,
            },
        },
    ]
    merged_prs = [
        {
            "number": 50,
            "title": "chore: tune prompt",
            "body": "Kaizen-Ref: KZ-2026-11-24-01",
            "createdAt": "2026-11-20T10:00:00Z",
            "mergedAt": "2026-11-20T12:00:00Z",
            "mergeCommit": {"oid": "d" * 40},
            "reviews": [{"state": "APPROVED"}],
        },
        {
            "number": 51,
            "title": "feat: one",
            "body": "",
            "createdAt": "2026-11-21T06:00:00Z",
            "mergedAt": "2026-11-21T12:00:00Z",
            "reviews": [{"state": "APPROVED"}],
        },
        {
            "number": 52,
            "title": "feat: two",
            "body": "",
            "createdAt": "2026-11-22T06:00:00Z",
            "mergedAt": "2026-11-22T12:00:00Z",
            "reviews": [{"state": "APPROVED"}],
        },
    ]

    # Case 1: KZ-01 passes (avg_review_rounds=1.0 < 2.0) and KZ-02 triggers rollback (avg_lead_time_hours=6.0 > 2.0).
    results = verify_proposals(
        proposals,
        merged_prs,
        {51: "live-gcp-verified", 52: "live-gcp-verified"},
        {"tool_error_rates": []},
        prior_snap,
    )
    by_id = {r["proposal_id"]: r for r in results}
    assert by_id["KZ-2026-11-24-01"]["status"] == "verified_pass"
    assert by_id["KZ-2026-11-24-02"]["status"] == "rollback_triggered"
    assert by_id["KZ-2026-11-24-02"]["revert_command"] == f"git revert {'c' * 40}"

    # Case 2: Anti-reward-hacking guard invalidates passing metric when live_gcp_verified_rate drops > 5%.
    hacked_results = verify_proposals(
        [proposals[0]],
        merged_prs,
        {51: "unit-test-verified", 52: "unit-test-verified"},
        {"tool_error_rates": []},
        prior_snap,
    )
    assert hacked_results[0]["status"] == "invalidated_regression"
    assert hacked_results[0]["revert_command"] == f"git revert {'d' * 40}"


def test_kaizen_collect_cli_degrades_gracefully_offline_hermetic(tmp_path: pathlib.Path) -> None:
    """Confirms core-gcp-fde/scripts/kaizen_collect.py runs hermetically offline and emits a valid snapshot."""
    out_file = tmp_path / "snapshot.json"
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("SCION_")}
    clean_env["HOME"] = str(tmp_path)
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/kaizen_collect.py"),
            "--repo",
            str(REPO_ROOT / "packs/gecx/repo-scaffold"),
            "--scratchpad",
            str(tmp_path / "missing-scratchpad"),
            "--history-dir",
            str(tmp_path / "snapshots"),
            "--out",
            str(out_file),
        ],
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["sources_status"]["hub_metrics"] == "skipped"
    assert data["sources_status"]["gcp_observability"] == "skipped"


def test_kaizen_verifier_hardening_and_cli_obs_json(tmp_path: pathlib.Path) -> None:
    """Negative tests (B-02/B-03/B-04/B-16/B-17/B-18/D-02): malformed JSONL, missing merged_at, commit trailers, and --gcp-obs-json."""
    from scripts.lib.kaizen_verifier import load_proposals

    props_file = tmp_path / "proposals.jsonl"
    valid_base = {
        "schema_version": "1",
        "proposal_id": "KZ-2026-11-24-01",
        "created_date_brt": "2026-11-24",
        "status": "proposed",
        "ladder_step": 2,
        "target_metric": "avg_review_rounds",
        "baseline_value": 3.0,
        "rollback_criterion": {
            "window_merged_prs": 1,
            "operator": "<=",
            "target_value": 2.0,
            "expected_delta_description": "Reduce review rounds below two.",
            "revert_target": "hub-project.yaml",
        },
        "anti_reward_hacking_attestation": {
            "preserves_code_reviewer": True,
            "preserves_evals_coverage": True,
            "preserves_iam_boundaries": True,
        },
    }
    updated = {**valid_base, "baseline_value": 2.5}
    props_file.write_text(
        json.dumps(valid_base) + "\n"
        + '{"proposal_id":"KZ-2026-11-24-99"}\n'  # schema-invalid, must be skipped without crash (B-02)
        + json.dumps(updated) + "\n",  # duplicate ID must deduplicate keeping last entry (B-04)
        encoding="utf-8",
    )
    loaded, errs = load_proposals(props_file)
    assert len(loaded) == 1 and loaded[0]["baseline_value"] == 2.5
    assert any("schema invalid" in e for e in errs)

    # Missing merged_at_utc on implemented proposal MUST stay measuring (never count pre-merge PRs, B-03).
    no_ts_res = verify_proposals(
        [{**valid_base, "status": "implemented", "merged_at_utc": None}],
        [{"number": 10, "createdAt": "2026-11-19T10:00:00", "mergedAt": "2026-11-19T11:00:00", "reviews": []}],
        {},
        {"tool_error_rates": []},
    )
    assert no_ts_res[0]["status"] == "measuring"
    assert no_ts_res[0]["prs_observed"] == 0

    # Unknown rollback operator must be rejected cleanly (B-17) and commit-body Kaizen-Ref must match (B-18).
    bad_op = {**valid_base, "rollback_criterion": {**valid_base["rollback_criterion"], "operator": "=="}}
    assert verify_proposals([bad_op], [], {}, {"tool_error_rates": []})[0]["status"] == "rejected"

    commit_ref_prs = [
        {
            "number": 60,
            "title": "chore: update limits",
            "body": "",
            "commits": [{"messageHeadline": "tune", "messageBody": "Kaizen-Ref: KZ-2026-11-24-01"}],
            "createdAt": "2026-11-20T10:00:00Z",
            "mergedAt": "2026-11-20T12:00:00Z",
            "reviews": [{"state": "APPROVED"}],
        },
        {
            "number": 61,
            "title": "feat: follow-up",
            "body": "",
            "createdAt": "2026-11-21T10:00:00",  # naive timestamp normalized to UTC (B-02)
            "mergedAt": "2026-11-21T11:00:00",
            "reviews": [{"state": "APPROVED"}],
        },
    ]
    matched = verify_proposals([valid_base], commit_ref_prs, {}, {"tool_error_rates": []})
    assert matched[0]["status"] == "verified_pass" and matched[0]["implemented_pr_number"] == 60

    # CLI --gcp-obs-json loads Tier-B JSON cleanly and archives dated snapshot into history_dir (D-02/B-06).
    obs_file = tmp_path / "obs.json"
    obs_file.write_text(json.dumps({"window_days": 7, "tokens_total": 42000}), encoding="utf-8")
    hist_dir = tmp_path / "history"
    out_snap = tmp_path / "snap-obs.json"
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("SCION_")}
    clean_env["HOME"] = str(tmp_path)
    res_obs = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/kaizen_collect.py"),
            "--repo", str(tmp_path),
            "--proposals", str(props_file),
            "--history-dir", str(hist_dir),
            "--gcp-obs-json", str(obs_file),
            "--out", str(out_snap),
        ],
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_obs.returncode == 0, res_obs.stderr
    obs_snap = json.loads(out_snap.read_text(encoding="utf-8"))
    assert obs_snap["sources_status"]["gcp_observability"] == "ok"
    assert obs_snap["gcp_observability"]["tokens_total"] == 42000
    assert list(hist_dir.glob("*.json"))
    assert (tmp_path / "proposals.state.json").is_file()
