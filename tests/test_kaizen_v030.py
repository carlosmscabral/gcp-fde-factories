"""Tests for the v0.3.0 0-token Kaizen collector, schema validation, and CLI entrypoint."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import yaml

from scripts.lib.kaizen_collector import build_kaizen_snapshot, write_validated_snapshot

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT_SCHEMA = REPO_ROOT / "schemas/kaizen-snapshot.schema.json"


def test_kaizen_collector_aggregates_all_tier_a_sources_and_validates(tmp_path: pathlib.Path) -> None:
    """Confirms build_kaizen_snapshot merges Tier A APIs, CLI, GitHub, scratchpad, and drift."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.poetry]\nname='demo'\n[tool.ruff]\n", encoding="utf-8")

    scratch = tmp_path / "scratchpad"
    scratch.mkdir()
    (scratch / "pr-7-verdict.json").write_text(json.dumps({"verdict": "live-gcp-verified"}), encoding="utf-8")
    (scratch / "pr-8-verdict.json").write_text(json.dumps({"verdict": "verifier-failed"}), encoding="utf-8")
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

    def fake_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict]:
        assert headers["X-Scion-Agent-Token"] == "tok-123"
        if "/projects/proj-1/metrics/summary" in url:
            return 200, {
                "totalTokens": 120000,
                "mostUsedTools": [
                    {"name": "run_command", "calls": 20, "error": 5},
                    {"name": "read_file", "calls": 40, "error": 0},
                ],
            }
        return 200, {"agentId": url.split("/")[-3], "tokens": 60000}

    def fake_run_cmd(cmd: list[str], cwd: pathlib.Path | None) -> tuple[int, str, str]:
        if cmd[:2] == ["scion", "list"]:
            return 0, json.dumps([
                {"id": "ag-1", "name": "dev-1", "phase": "running", "activity": "limits_exceeded"},
                {"id": "ag-2", "name": "rev-1", "phase": "stalled", "activity": "offline"},
            ]), ""
        if cmd[:2] == ["scion", "artifact"]:
            return 0, json.dumps({"artifacts": [{"id": "a1"}, {"id": "a2"}]}), ""
        if cmd[:2] == ["scion", "decisions"]:
            return 0, json.dumps([{"id": "d1"}]), ""
        if cmd[:2] == ["gh", "pr"]:
            return 0, json.dumps([
                {
                    "number": 7,
                    "createdAt": "2026-11-20T10:00:00Z",
                    "mergedAt": "2026-11-20T14:00:00Z",
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
    assert out_path.exists()

    assert snap["sources_status"]["hub_metrics"] == "ok"
    assert snap["sources_status"]["scion_control_plane"] == "ok"
    assert snap["sources_status"]["github_ci"] == "ok"
    assert snap["sources_status"]["scratchpad"] == "ok"
    assert snap["sources_status"]["repo_drift"] == "ok"
    assert snap["sources_status"]["gcp_observability"] == "skipped"

    assert snap["hub_metrics"]["tool_error_rates"][0] == {
        "tool": "run_command",
        "calls": 20,
        "errors": 5,
        "error_rate": 0.25,
    }
    assert snap["control_plane"]["stalled_agents"] == ["rev-1"]
    assert snap["control_plane"]["limits_exceeded_agents"] == ["dev-1"]
    assert snap["control_plane"]["artifacts_count"] == 2
    assert snap["github_ci"]["avg_review_rounds"] == 2.0
    assert snap["github_ci"]["avg_lead_time_hours"] == 4.0
    assert snap["github_ci"]["failed_ci_runs"] == 1
    assert snap["scratchpad"]["verdict_counts"] == {"live-gcp-verified": 1, "verifier-failed": 1}
    assert [w["id"] for w in snap["scratchpad"]["workarounds_expiring_soon"]] == ["WK-101"]
    assert snap["repo_drift"]["drift_detected"] is True
    assert "poetry" in snap["repo_drift"]["missing_binaries"]


def test_kaizen_collect_cli_degrades_gracefully_offline(tmp_path: pathlib.Path) -> None:
    """Confirms core-gcp-fde/scripts/kaizen_collect.py runs offline and emits a valid snapshot."""
    out_file = tmp_path / "snapshot.json"
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core-gcp-fde/scripts/kaizen_collect.py"),
            "--repo",
            str(REPO_ROOT / "packs/gecx/repo-scaffold"),
            "--scratchpad",
            str(tmp_path / "missing-scratchpad"),
            "--out",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["sources_status"]["hub_metrics"] == "skipped"
    assert data["sources_status"]["gcp_observability"] == "skipped"
