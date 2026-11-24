"""Orchestrator for 0-token Kaizen telemetry collection and schema validation (v0.3.0).

Combines Tier A sources (Scion Hub Metrics API, Control Plane, GitHub/CI, Scratchpad),
optional Day-2 repo drift detection (v0.4.0 Scanner hook), and optional Tier B GCP
Cloud Monitoring/Logging queries into one schema-validated kaizen-snapshot.json file.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any

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
from scripts.lib.schema_validator import validate_against_schema


def _collect_optional_drift(
    repo_dir: pathlib.Path | None,
    toolchain_manifest: pathlib.Path | None,
) -> tuple[str, dict[str, Any]]:
    """Runs the static brownfield scanner in drift mode when a repo and manifest exist."""
    empty = {"drift_detected": False, "missing_binaries": [], "notes": []}
    if not (repo_dir and repo_dir.exists()):
        return "skipped", empty
    try:
        from scripts.lib.onboard_scanner import detect_repo_drift
    except ImportError:
        return "skipped", empty

    drift = detect_repo_drift(repo_dir, toolchain_manifest)
    return "ok", drift


def build_kaizen_snapshot(
    hub_url: str = "",
    project_id: str = "",
    agent_token: str = "",
    repo_dir: pathlib.Path | None = None,
    scratchpad_dir: pathlib.Path | None = None,
    workarounds_path: pathlib.Path | None = None,
    toolchain_manifest: pathlib.Path | None = None,
    include_drift: bool = True,
    enable_gcp_obs: bool = False,
    gcp_obs_payload: dict[str, Any] | None = None,
    today: dt.date | None = None,
    http_get: HttpGetFn = default_http_get,
    run_cmd: RunCmdFn = default_run_cmd,
) -> dict[str, Any]:
    """Collects all configured telemetry sources and returns a Kaizen snapshot dict."""
    cp_status, cp_data, agent_ids = collect_control_plane(hub_url, run_cmd=run_cmd)
    hm_status, hm_data = collect_hub_metrics(
        hub_url, project_id, agent_token, agent_ids, http_get=http_get
    )
    gh_status, gh_data = collect_github_ci(repo_dir, run_cmd=run_cmd)
    sp_status, sp_data = collect_scratchpad(scratchpad_dir, workarounds_path, today=today)

    if include_drift:
        dr_status, dr_data = _collect_optional_drift(repo_dir, toolchain_manifest)
    else:
        dr_status, dr_data = "skipped", {"drift_detected": False, "missing_binaries": [], "notes": []}

    if enable_gcp_obs and gcp_obs_payload is not None:
        obs_status, obs_data = "ok", gcp_obs_payload
    else:
        obs_status, obs_data = "skipped", None

    return {
        "schema_version": "1",
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "hub_project_id": project_id or None,
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
    }


def write_validated_snapshot(
    snapshot: dict[str, Any],
    out_path: pathlib.Path,
    schema_path: pathlib.Path,
) -> list[str]:
    """Validates snapshot against kaizen-snapshot.schema.json and writes it when valid."""
    errors = validate_against_schema(snapshot, schema_path)
    if errors:
        return errors
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return []
