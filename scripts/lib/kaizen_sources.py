"""Scion Hub HTTP and CLI telemetry adapters for the 0-token Kaizen collector (v0.3.0).

Uses verified Scion v0.4.0-preview.3 flags (--format json for list and artifact list,
--all --json for decisions list), blocks insecure non-loopback HTTP and cross-host redirects,
and re-exports repository/GitHub adapters from kaizen_repo_sources.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from scripts.lib.kaizen_repo_sources import (
    ALLOWED_VERDICTS,
    RunCmdFn,
    clean_token_str,
    collect_github_ci as _collect_github_ci,
    collect_scratchpad,
)

HttpGetFn = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


def _is_safe_hub_url(hub_url: str) -> bool:
    """Allows HTTPS URLs and loopback HTTP endpoints only."""
    parsed = urllib.parse.urlparse(hub_url)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return True
    return False


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Blocks HTTP redirects to a different host so auth headers never leak."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_host = urllib.parse.urlparse(req.full_url).netloc
        new_host = urllib.parse.urlparse(newurl).netloc
        if old_host != new_host:
            raise urllib.error.HTTPError(newurl, code, "Blocked cross-host redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_hub_auth_header() -> dict[str, str]:
    """Selects canonical agent token file, bootstrap agent token, or user Bearer token."""
    token_file = os.environ.get("SCION_TOKEN_FILE") or str(pathlib.Path.home() / ".scion" / "scion-token")
    tpath = pathlib.Path(token_file)
    if tpath.is_file():
        tok = tpath.read_text(encoding="utf-8", errors="ignore").strip()
        if tok:
            return {"X-Scion-Agent-Token": tok}
    agent_tok = os.environ.get("SCION_AUTH_TOKEN", "").strip()
    if agent_tok:
        return {"X-Scion-Agent-Token": agent_tok}
    user_tok = os.environ.get("SCION_HUB_TOKEN", "").strip()
    if user_tok:
        return {"Authorization": f"Bearer {user_tok}"}
    return {}


def default_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """Sends an authenticated HTTP GET without cross-host redirect forwarding."""
    if not _is_safe_hub_url(url):
        return 0, {"error": f"Blocked insecure non-loopback HTTP URL: {url}"}
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_NoCrossHostRedirect)
    try:
        with opener.open(req, timeout=20) as resp:
            decoded = json.loads(resp.read().decode("utf-8"))
            return resp.status, decoded if isinstance(decoded, dict) else {"data": decoded}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
        return code, {"error": clean_token_str(exc, 180)}


def default_run_cmd(cmd: list[str], cwd: pathlib.Path | None = None) -> tuple[int, str, str]:
    """Runs an external CLI command and returns exit code, stdout, and stderr."""
    try:
        res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=30)
        return res.returncode, res.stdout, res.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", clean_token_str(exc, 180)


def collect_github_ci(
    repo_dir: pathlib.Path | None,
    run_cmd: RunCmdFn = default_run_cmd,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[str]]:
    """Collects merged PR review rounds, lead times, CI failures, and hygiene issues."""
    return _collect_github_ci(repo_dir, run_cmd)


def collect_hub_metrics(
    hub_url: str,
    project_id: str,
    auth_headers: dict[str, str],
    agent_ids: list[str],
    http_get: HttpGetFn = default_http_get,
) -> tuple[str, dict[str, Any], list[str]]:
    """Queries Scion Hub Session Metrics API for project and per-agent summaries."""
    empty = {
        "project_summary": None,
        "agents": [],
        "tool_error_rates": [],
        "window_note": "Scion Hub aggregates all-time totals and top-10 tools across the newest 100 sessions.",
    }
    if not (hub_url and project_id and auth_headers):
        return "skipped", empty, []
    if not _is_safe_hub_url(hub_url):
        return "error", empty, [f"hub_metrics: blocked insecure URL {hub_url}"]

    base = hub_url.rstrip("/")
    headers = {**auth_headers, "Accept": "application/json"}
    status, proj = http_get(f"{base}/api/v1/projects/{project_id}/metrics/summary", headers)
    if status != 200 or not isinstance(proj, dict):
        return "error", empty, [f"hub_metrics: project summary returned HTTP {status}"]

    agents_out: list[dict[str, Any]] = []
    for aid in agent_ids:
        a_status, a_body = http_get(f"{base}/api/v1/agents/{aid}/metrics/summary", headers)
        if a_status == 200 and isinstance(a_body, dict):
            agents_out.append(a_body)

    tool_rates: list[dict[str, Any]] = []
    raw_tools = proj.get("mostUsedTools")
    if isinstance(raw_tools, list):
        for tool in raw_tools:
            if not isinstance(tool, dict):
                continue
            calls = max(0, int(tool.get("calls", 0) or 0))
            errors = max(0, int(tool.get("error", 0) or 0))
            if calls > 0:
                tool_rates.append({
                    "tool": clean_token_str(tool.get("name", "unknown"), 80),
                    "calls": calls,
                    "errors": errors,
                    "error_rate": min(1.0, round(errors / calls, 4)),
                })
    tool_rates.sort(key=lambda item: (-item["error_rate"], -item["calls"]))
    return "ok", {**empty, "project_summary": proj, "agents": agents_out, "tool_error_rates": tool_rates}, []


def _count_json_items(cmd: list[str], run_cmd: RunCmdFn) -> int | None:
    """Returns list length from a Scion JSON CLI command, or None when unavailable."""
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


def collect_control_plane(
    hub_url: str,
    run_cmd: RunCmdFn = default_run_cmd,
) -> tuple[str, dict[str, Any], list[str], list[str]]:
    """Inspects live Scion agents, stalls, limits_exceeded flags, artifacts, and decisions."""
    empty = {
        "agent_count": 0,
        "stalled_agents": [],
        "limits_exceeded_agents": [],
        "artifacts_count": None,
        "decisions_count": None,
    }
    if not hub_url:
        return "skipped", empty, [], []

    rc, out, err = run_cmd(["scion", "--format", "json", "list", "--hub", hub_url], None)
    if rc == 127:
        return "skipped", empty, [], []
    if rc != 0:
        return "error", empty, [], [f"scion_control_plane: list failed (rc={rc}): {clean_token_str(err, 120)}"]

    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return "error", empty, [], ["scion_control_plane: invalid JSON from scion list"]

    agents = raw if isinstance(raw, list) else (raw.get("agents", []) if isinstance(raw, dict) else [])
    if not isinstance(agents, list):
        return "error", empty, [], ["scion_control_plane: unexpected root type from scion list"]

    stalled: list[str] = []
    limits_hit: list[str] = []
    agent_ids: list[str] = []
    for ag in agents:
        if not isinstance(ag, dict):
            continue
        name = clean_token_str(ag.get("name") or ag.get("slug") or ag.get("id"), 80)
        aid = clean_token_str(ag.get("id") or name, 80)
        if aid:
            agent_ids.append(aid)
        fields = " ".join(
            str(ag.get(k) or "").lower()
            for k in ("phase", "status", "activity", "detail", "exitReason", "suspendReason")
        )
        if "stall" in fields and name:
            stalled.append(name)
        if "limits_exceeded" in fields and name:
            limits_hit.append(name)

    art_count = _count_json_items(["scion", "--format", "json", "artifact", "list", "--all", "--hub", hub_url], run_cmd)
    dec_count = _count_json_items(["scion", "decisions", "list", "--all", "--json", "--hub", hub_url], run_cmd)
    return "ok", {
        "agent_count": len(agents),
        "stalled_agents": sorted(set(stalled)),
        "limits_exceeded_agents": sorted(set(limits_hit)),
        "artifacts_count": art_count,
        "decisions_count": dec_count,
    }, agent_ids, []


__all__ = [
    "ALLOWED_VERDICTS",
    "HttpGetFn",
    "RunCmdFn",
    "collect_control_plane",
    "collect_github_ci",
    "collect_hub_metrics",
    "collect_scratchpad",
    "default_http_get",
    "default_run_cmd",
    "resolve_hub_auth_header",
]
