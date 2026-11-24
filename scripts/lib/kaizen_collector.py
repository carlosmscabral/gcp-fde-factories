"""Orchestrator for 0-token Kaizen telemetry collection, closed-loop proposal verification, and snapshot history.

Combines Tier A sources, Day-2 repo drift detection, dated snapshot history deltas, and
deterministic proposal verification (`verified_pass` / `rollback_triggered` / `invalidated_regression`).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.kaizen_sources import (
    HttpGetFn,
    RunCmdFn,
    collect_control_plane,
    collect_github_ci,
    collect_hub_metrics,
    collect_scratchpad,
    default_http_get,
    default_run_cmd,
)
from scripts.lib.kaizen_verifier import (
    load_latest_prior_snapshot,
    load_proposals,
    verify_proposals,
    write_proposal_state,
)
from scripts.lib.schema_validator import validate_against_schema


def _collect_optional_drift(
    repo_dir: pathlib.Path | None,
    toolchain_manifest: pathlib.Path | None,
) -> tuple[str, dict[str, Any], list[str]]:
    """Runs the static brownfield scanner in drift mode with safe error degradation."""
    empty = {"drift_detected": False, "missing_binaries": [], "notes": []}
    if not (repo_dir and repo_dir.exists()):
        return "skipped", empty, []
    try:
        from scripts.lib.onboard_scanner import detect_repo_drift

        return "ok", detect_repo_drift(repo_dir, toolchain_manifest), []
    except Exception as exc:
        return "error", empty, [f"repo_drift: scan failed: {exc}"]


def _resolve_proposals_path(
    explicit: pathlib.Path | None,
    repo_dir: pathlib.Path | None,
    scratchpad_dir: pathlib.Path | None,
) -> pathlib.Path | None:
    """Resolves the proposal registry from explicit path, .factory/kaizen/, or scratchpad."""
    candidates = [
        explicit,
        (repo_dir / ".factory" / "kaizen" / "proposals.jsonl") if repo_dir else None,
        (scratchpad_dir / "kaizen-proposals.jsonl") if scratchpad_dir else None,
    ]
    for cand in candidates:
        if cand and cand.is_file():
            return cand
    return None


def build_kaizen_snapshot(
    hub_url: str = "",
    project_id: str = "",
    agent_token: str = "",
    auth_headers: dict[str, str] | None = None,
    repo_dir: pathlib.Path | None = None,
    scratchpad_dir: pathlib.Path | None = None,
    verdicts_dir: pathlib.Path | None = None,
    workarounds_path: pathlib.Path | None = None,
    proposals_path: pathlib.Path | None = None,
    history_dir: pathlib.Path | None = None,
    toolchain_manifest: pathlib.Path | None = None,
    include_drift: bool = True,
    enable_gcp_obs: bool = False,
    gcp_obs_payload: dict[str, Any] | None = None,
    today: dt.date | None = None,
    time_zone: str = "America/Sao_Paulo",
    http_get: HttpGetFn = default_http_get,
    run_cmd: RunCmdFn = default_run_cmd,
) -> dict[str, Any]:
    """Collects telemetry, evaluates open Kaizen proposals, and returns a snapshot dict."""
    resolved_auth = dict(auth_headers or {})
    if not resolved_auth and agent_token:
        resolved_auth = {"X-Scion-Agent-Token": agent_token}

    all_errors: list[str] = []
    cp_status, cp_data, agent_ids, cp_errs = collect_control_plane(hub_url, run_cmd=run_cmd)
    all_errors.extend(cp_errs)

    hm_status, hm_data, hm_errs = collect_hub_metrics(
        hub_url, project_id, resolved_auth, agent_ids, http_get=http_get
    )
    all_errors.extend(hm_errs)

    gh_status, gh_data, merged_prs, gh_errs = collect_github_ci(repo_dir, run_cmd=run_cmd)
    all_errors.extend(gh_errs)

    resolved_verdicts = verdicts_dir or (repo_dir / ".factory" / "verdicts" if repo_dir else None)
    backlog_path = (repo_dir / ".factory" / "modernization-backlog.yaml") if repo_dir else None
    sp_status, sp_data, verdicts_by_pr, sp_errs = collect_scratchpad(
        scratchpad_dir,
        resolved_verdicts,
        workarounds_path,
        backlog_path=backlog_path,
        today=today,
        time_zone=time_zone,
    )
    all_errors.extend(sp_errs)

    if include_drift:
        dr_status, dr_data, dr_errs = _collect_optional_drift(repo_dir, toolchain_manifest)
        all_errors.extend(dr_errs)
    else:
        dr_status, dr_data = "skipped", {"drift_detected": False, "missing_binaries": [], "notes": []}

    if enable_gcp_obs:
        if gcp_obs_payload is not None:
            obs_status, obs_data = "ok", gcp_obs_payload
        else:
            obs_status, obs_data = "error", None
            all_errors.append(
                "gcp_observability: --enable-gcp-obs set but no Cloud Monitoring/Logging adapter payload was supplied."
            )
    else:
        obs_status, obs_data = "skipped", None

    ref_date_str = (today or dt.datetime.now(ZoneInfo(time_zone)).date()).isoformat()
    resolved_history = history_dir or ((repo_dir / ".factory" / "kaizen" / "snapshots") if repo_dir else None)
    prior_snap = load_latest_prior_snapshot(resolved_history, ref_date_str)
    prop_file = _resolve_proposals_path(proposals_path, repo_dir, scratchpad_dir)
    proposals, prop_errs = load_proposals(prop_file)
    all_errors.extend(prop_errs)
    verifications = verify_proposals(proposals, merged_prs, verdicts_by_pr, hm_data, prior_snapshot=prior_snap)

    return {
        "schema_version": "1",
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "hub_project_id": project_id or None,
        "time_zone": time_zone,
        "sources_status": {
            "hub_metrics": hm_status,
            "scion_control_plane": cp_status,
            "github_ci": gh_status,
            "scratchpad": sp_status,
            "repo_drift": dr_status,
            "gcp_observability": obs_status,
        },
        "hub_metrics": hm_data,
        "control_plane": cp_data,
        "github_ci": gh_data,
        "scratchpad": sp_data,
        "repo_drift": dr_data,
        "gcp_observability": obs_data,
        "proposal_verifications": verifications,
        "source_errors": [e[:240] for e in all_errors],
    }


def write_validated_snapshot(
    snapshot: dict[str, Any],
    out_path: pathlib.Path,
    schema_path: pathlib.Path,
    history_dir: pathlib.Path | None = None,
    today: dt.date | None = None,
    proposal_state_path: pathlib.Path | None = None,
) -> list[str]:
    """Validates snapshot against schema, writes out_path, archives dated history, and persists proposal state."""
    errors = validate_against_schema(snapshot, schema_path)
    if errors:
        return errors
    rendered = json.dumps(snapshot, indent=2) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    if history_dir is not None:
        tz = str(snapshot.get("time_zone") or "America/Sao_Paulo")
        date_slug = (today or dt.datetime.now(ZoneInfo(tz)).date()).isoformat()
        history_dir.mkdir(parents=True, exist_ok=True)
        (history_dir / f"{date_slug}.json").write_text(rendered, encoding="utf-8")
    if proposal_state_path is not None and snapshot.get("proposal_verifications"):
        write_proposal_state(proposal_state_path, snapshot["proposal_verifications"])
    return []
