"""Zero-token Tier-B Google Cloud Monitoring and Cloud Logging collector for Kaizen (HC-04 F5).

Queries Vertex AI online serving invocation counts in inference_project_id and recent Sandbox
runtime logs in sandbox_project_id using standard library urllib only. Supports explicit tokens,
GCE/GKE metadata server credentials, or gcloud CLI fallback without introducing SDK weight.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

GcpHttpFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, dict[str, Any]]]


def resolve_gcp_access_token() -> str:
    """Resolves a short-lived GCP OAuth token from env, metadata server, or gcloud CLI."""
    env_tok = os.environ.get("GCP_ACCESS_TOKEN", "").strip()
    if env_tok:
        return env_tok

    # Prefer the GCE or GKE Workload Identity metadata endpoint inside factory containers.
    meta_url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    meta_req = urllib.request.Request(meta_url, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(meta_req, timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            tok = str(payload.get("access_token") or "").strip()
            if tok:
                return tok
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass

    try:
        res = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            text=True,
            capture_output=True,
            timeout=10,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def default_gcp_http(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Executes a JSON HTTPS request against Google Cloud REST APIs."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = dict(headers)
    if data is not None:
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            decoded = json.loads(resp.read().decode("utf-8"))
            return resp.status, decoded if isinstance(decoded, dict) else {"data": decoded}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:240]
        return exc.code, {"error": body}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return 0, {"error": str(exc)[:240]}


def collect_gcp_observability(
    inference_project: str,
    sandbox_project: str,
    window_hours: int = 24,
    access_token: str = "",
    http_fn: GcpHttpFn = default_gcp_http,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Collects Vertex AI Monitoring counts and Sandbox Cloud Logging severity summaries."""
    if not inference_project and not sandbox_project:
        return (
            "error",
            None,
            ["gcp_observability: provide --inference-project/--sandbox-project or --gcp-obs-json when --enable-gcp-obs is set."],
        )

    token = access_token.strip() or resolve_gcp_access_token()
    if not token:
        return "error", None, ["gcp_observability: failed to resolve a GCP OAuth access token."]

    now = dt.datetime.now(dt.timezone.utc)
    clamped_hours = max(1, min(168, int(window_hours)))
    start = (now - dt.timedelta(hours=clamped_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    errors: list[str] = []
    summary: dict[str, Any] = {"window_utc": {"start": start, "end": end}}

    if inference_project:
        query = urllib.parse.urlencode({
            "filter": 'metric.type = "aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"',
            "interval.startTime": start,
            "interval.endTime": end,
        })
        mon_url = f"https://monitoring.googleapis.com/v3/projects/{inference_project}/timeSeries?{query}"
        headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": inference_project}
        code, body = http_fn(mon_url, "GET", headers, None)
        if code == 200:
            series = body.get("timeSeries", []) if isinstance(body.get("timeSeries"), list) else []
            invocations = 0
            by_model: dict[str, int] = {}
            for ts in series:
                model_id = str(ts.get("resource", {}).get("labels", {}).get("model_user_id") or "unknown")
                for pt in ts.get("points", []):
                    val = int(pt.get("value", {}).get("int64Value") or 0)
                    invocations += val
                    by_model[model_id] = by_model.get(model_id, 0) + val
            summary["inference_monitoring"] = {
                "project_id": inference_project,
                "time_series_count": len(series),
                "total_model_invocations": invocations,
                "invocations_by_model": by_model,
            }
        else:
            errors.append(f"gcp_observability: Cloud Monitoring query returned HTTP {code}")

    if sandbox_project:
        log_url = "https://logging.googleapis.com/v2/entries:list"
        headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": sandbox_project}
        req_body = {
            "resourceNames": [f"projects/{sandbox_project}"],
            "filter": f'timestamp >= "{start}"',
            "pageSize": 50,
            "orderBy": "timestamp desc",
        }
        code, body = http_fn(log_url, "POST", headers, req_body)
        if code == 200:
            entries = body.get("entries", []) if isinstance(body.get("entries"), list) else []
            severities: dict[str, int] = {}
            cloud_run_count = 0
            for entry in entries:
                sev = str(entry.get("severity") or "DEFAULT")
                severities[sev] = severities.get(sev, 0) + 1
                if "cloud_run" in str(entry.get("resource", {}).get("type") or ""):
                    cloud_run_count += 1
            summary["sandbox_logging"] = {
                "project_id": sandbox_project,
                "entries_sampled": len(entries),
                "cloud_run_entries": cloud_run_count,
                "severity_counts": severities,
            }
        else:
            errors.append(f"gcp_observability: Cloud Logging query returned HTTP {code}")

    if errors:
        return "error", summary if len(summary) > 1 else None, errors
    return "ok", summary, []
