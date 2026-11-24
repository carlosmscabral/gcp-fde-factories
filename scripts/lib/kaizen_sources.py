"""Telemetry source adapters for the 0-token Kaizen collector (v0.3.0).

Reads Tier A sources without extra IAM grants (Scion Hub Session Metrics API,
Scion CLI control plane, GitHub CLI PR/CI state, and shared scratchpad files).
Reads optional Tier B GCP observability only when explicitly enabled.
Every adapter degrades gracefully when an external endpoint or tool is absent.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable

from scripts.lib.io_utils import load_yaml

HttpGetFn = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]
RunCmdFn = Callable[[list[str], pathlib.Path | None], tuple[int, str, str]]


def default_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """Sends an authenticated HTTP GET request and decodes the JSON body."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
        return code, {"error": str(exc)}


def default_run_cmd(cmd: list[str], cwd: pathlib.Path | None = None) -> tuple[int, str, str]:
    """Runs an external CLI command and returns exit code, stdout, and stderr."""
    try:
        res = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=30,
        )
        return res.returncode, res.stdout, res.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def collect_hub_metrics(
    hub_url: str,
    project_id: str,
    agent_token: str,
    agent_ids: list[str],
    http_get: HttpGetFn = default_http_get,
) -> tuple[str, dict[str, Any]]:
    """Queries Scion Hub Session Metrics API for project and per-agent summaries."""
    empty = {"project_summary": None, "agents": [], "tool_error_rates": []}
    if not (hub_url and project_id and agent_token):
        return "skipped", empty

    base = hub_url.rstrip("/")
    headers = {"X-Scion-Agent-Token": agent_token, "Accept": "application/json"}
    status, proj = http_get(f"{base}/api/v1/projects/{project_id}/metrics/summary", headers)
    if status != 200:
        return "error", empty

    agents_out: list[dict[str, Any]] = []
    for aid in agent_ids:
        a_status, a_body = http_get(f"{base}/api/v1/agents/{aid}/metrics/summary", headers)
        if a_status == 200:
            agents_out.append(a_body)

    tool_rates: list[dict[str, Any]] = []
    for tool in proj.get("mostUsedTools", []) or []:
        calls = int(tool.get("calls", 0) or 0)
        errors = int(tool.get("error", 0) or 0)
        if calls > 0:
            tool_rates.append({
                "tool": str(tool.get("name", "unknown")),
                "calls": calls,
                "errors": errors,
                "error_rate": round(errors / calls, 4),
            })
    tool_rates.sort(key=lambda item: (-item["error_rate"], -item["calls"]))
    return "ok", {"project_summary": proj, "agents": agents_out, "tool_error_rates": tool_rates}


def collect_control_plane(
    hub_url: str,
    run_cmd: RunCmdFn = default_run_cmd,
) -> tuple[str, dict[str, Any], list[str]]:
    """Inspects live Scion agents, stalls, limits_exceeded flags, artifacts, and decisions."""
    empty = {
        "agent_count": 0,
        "stalled_agents": [],
        "limits_exceeded_agents": [],
        "artifacts_count": None,
        "decisions_count": None,
    }
    if not hub_url:
        return "skipped", empty, []

    rc, out, _ = run_cmd(["scion", "list", "--json", "--hub", hub_url], None)
    if rc != 0:
        return "error", empty, []

    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return "error", empty, []

    agents = raw if isinstance(raw, list) else raw.get("agents", [])
    stalled: list[str] = []
    limits_hit: list[str] = []
    agent_ids: list[str] = []

    for ag in agents:
        name = str(ag.get("name") or ag.get("slug") or ag.get("id") or "")
        aid = str(ag.get("id") or name)
        if aid:
            agent_ids.append(aid)
        phase = str(ag.get("phase") or ag.get("status") or "").lower()
        activity = str(ag.get("activity") or "").lower()
        detail = str(ag.get("detail") or "").lower()
        if "stall" in phase or "stall" in activity or "offline" in activity:
            stalled.append(name)
        if "limits_exceeded" in activity or "limits_exceeded" in detail:
            limits_hit.append(name)

    art_count = _count_json_items(["scion", "artifact", "list", "--json", "--hub", hub_url], run_cmd)
    dec_count = _count_json_items(["scion", "decisions", "list", "--json", "--hub", hub_url], run_cmd)

    return "ok", {
        "agent_count": len(agents),
        "stalled_agents": sorted(stalled),
        "limits_exceeded_agents": sorted(limits_hit),
        "artifacts_count": art_count,
        "decisions_count": dec_count,
    }, agent_ids


def _count_json_items(cmd: list[str], run_cmd: RunCmdFn) -> int | None:
    """Returns list length from a Scion JSON CLI command, or None if unavailable."""
    rc, out, _ = run_cmd(cmd, None)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("items", "artifacts", "decisions"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return None


def collect_github_ci(
    repo_dir: pathlib.Path | None,
    run_cmd: RunCmdFn = default_run_cmd,
) -> tuple[str, dict[str, Any]]:
    """Collects merged PR review rounds, lead times, CI failures, and open hygiene issues."""
    empty = {
        "merged_prs": 0,
        "avg_review_rounds": None,
        "avg_lead_time_hours": None,
        "failed_ci_runs": 0,
        "hygiene_issues_open": 0,
    }
    if not repo_dir or not repo_dir.exists():
        return "skipped", empty

    rc, pr_out, _ = run_cmd(
        ["gh", "pr", "list", "--state", "merged", "--limit", "25", "--json", "number,createdAt,mergedAt,reviews"],
        repo_dir,
    )
    if rc != 0:
        return "skipped", empty

    try:
        prs = json.loads(pr_out)
    except json.JSONDecodeError:
        return "error", empty

    lead_hours: list[float] = []
    review_rounds: list[int] = []
    for pr in prs:
        created = _parse_iso(pr.get("createdAt"))
        merged = _parse_iso(pr.get("mergedAt"))
        if created and merged and merged >= created:
            lead_hours.append((merged - created).total_seconds() / 3600.0)
        reviews = pr.get("reviews") or []
        changes_requested = sum(1 for r in reviews if str(r.get("state", "")).upper() == "CHANGES_REQUESTED")
        review_rounds.append(changes_requested + (1 if reviews else 0))

    failed_runs = 0
    rc_run, run_out, _ = run_cmd(["gh", "run", "list", "--limit", "30", "--json", "conclusion"], repo_dir)
    if rc_run == 0:
        try:
            runs = json.loads(run_out)
            failed_runs = sum(1 for r in runs if str(r.get("conclusion", "")).lower() == "failure")
        except json.JSONDecodeError:
            pass

    hygiene_open = 0
    rc_iss, iss_out, _ = run_cmd(
        ["gh", "issue", "list", "--state", "open", "--label", "priority:hygiene", "--json", "number"],
        repo_dir,
    )
    if rc_iss == 0:
        try:
            hygiene_open = len(json.loads(iss_out))
        except json.JSONDecodeError:
            pass

    return "ok", {
        "merged_prs": len(prs),
        "avg_review_rounds": round(sum(review_rounds) / len(review_rounds), 2) if review_rounds else None,
        "avg_lead_time_hours": round(sum(lead_hours) / len(lead_hours), 2) if lead_hours else None,
        "failed_ci_runs": failed_runs,
        "hygiene_issues_open": hygiene_open,
    }


def collect_scratchpad(
    scratchpad_dir: pathlib.Path | None,
    workarounds_path: pathlib.Path | None,
    today: dt.date | None = None,
    expiring_window_days: int = 15,
) -> tuple[str, dict[str, Any]]:
    """Aggregates Verdict history, Sandbox ledger count, Kaizen events, and expiring workarounds."""
    ref_day = today or dt.date.today()
    verdict_counts: dict[str, int] = {}
    ledger_count = 0
    events_count = 0

    if scratchpad_dir and scratchpad_dir.exists():
        for vf in sorted(scratchpad_dir.rglob("*verdict*.json")):
            try:
                data = json.loads(vf.read_text(encoding="utf-8"))
                lvl = str(data.get("verdict", "unknown"))
                verdict_counts[lvl] = verdict_counts.get(lvl, 0) + 1
            except (OSError, json.JSONDecodeError):
                continue
        ledger = scratchpad_dir / "sandbox-ledger.jsonl"
        if ledger.exists():
            ledger_count = sum(1 for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip())
        events = scratchpad_dir / "kaizen-events.jsonl"
        if events.exists():
            events_count = sum(1 for ln in events.read_text(encoding="utf-8").splitlines() if ln.strip())

    expiring: list[dict[str, Any]] = []
    if workarounds_path and workarounds_path.exists():
        cfg = load_yaml(workarounds_path)
        for item in cfg.get("workarounds", []) or []:
            expires = dt.date.fromisoformat(str(item["expires_date"]))
            remaining = (expires - ref_day).days
            if remaining <= expiring_window_days:
                expiring.append({
                    "id": str(item["id"]),
                    "component": str(item["component"]),
                    "days_remaining": remaining,
                })

    has_any = bool(
        (scratchpad_dir and scratchpad_dir.exists())
        or (workarounds_path and workarounds_path.exists())
    )
    return ("ok" if has_any else "skipped"), {
        "verdict_counts": verdict_counts,
        "sandbox_ledger_entries": ledger_count,
        "kaizen_events_count": events_count,
        "workarounds_expiring_soon": expiring,
    }


def _parse_iso(raw: Any) -> dt.datetime | None:
    """Parses an ISO-8601 UTC timestamp string into an aware datetime."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
