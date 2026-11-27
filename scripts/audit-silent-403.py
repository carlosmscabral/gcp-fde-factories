#!/usr/bin/env python3
"""Zero-Silent-403 Cloud Logging and Audit Log scanner for Hillclimbing qualification gates.

Scans GCP Cloud Logging across Hub, Inference, and Sandbox projects for silent background
PERMISSION_DENIED, HTTP 403, SERVICE_DISABLED, or OTLP exporter errors emitted by factory
Service Accounts or deployed Agent Engine runtimes even when synchronous HTTP responses succeed.
Exits 0 only when zero unexpected denials appear outside explicit intentional probe allowlists.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

SILENT_DENIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bPERMISSION_DENIED\b", re.IGNORECASE),
    re.compile(r"\bSERVICE_DISABLED\b", re.IGNORECASE),
    re.compile(r"\b403\s+Forbidden\b", re.IGNORECASE),
    re.compile(r"Failed to export (?:spans|batch|logs|metrics)", re.IGNORECASE),
    re.compile(r"status\s*[:=]\s*403\b", re.IGNORECASE),
    re.compile(r"User not authorized to perform", re.IGNORECASE),
)

DEFAULT_INTENTIONAL_PROBE_EXCLUSIONS: tuple[str, ...] = (
    "userStores/default_user_store/userLicenses",
    "hc12-deployer-probes",
    "negative-probe",
)


def classify_log_entries(
    entries: list[dict[str, Any]],
    allowlist_substrings: tuple[str, ...] = DEFAULT_INTENTIONAL_PROBE_EXCLUSIONS,
) -> list[dict[str, Any]]:
    """Filters raw Cloud Logging entries and returns unexpected silent 403 or exporter failures."""
    findings: list[dict[str, Any]] = []
    for entry in entries:
        blob = json.dumps(entry, sort_keys=True)
        if any(marker and marker in blob for marker in allowlist_substrings):
            continue
        matched = [pat.pattern for pat in SILENT_DENIAL_PATTERNS if pat.search(blob)]
        if not matched:
            continue
        proto = entry.get("protoPayload") or {}
        text = str(entry.get("textPayload") or "")
        jp = entry.get("jsonPayload") or {}
        msg = text or str(jp.get("message") or proto.get("status", {}).get("message") or blob[:240])
        findings.append(
            {
                "timestamp": entry.get("timestamp"),
                "severity": entry.get("severity"),
                "logName": entry.get("logName"),
                "resource": (entry.get("resource") or {}).get("type"),
                "principal": (proto.get("authenticationInfo") or {}).get("principalEmail"),
                "method": proto.get("methodName"),
                "matched_patterns": matched,
                "message": msg[:320],
            }
        )
    return findings


def fetch_project_denial_entries(
    project_id: str,
    since_rfc3339: str,
    token: str,
    page_size: int = 200,
) -> list[dict[str, Any]]:
    """Queries Cloud Logging v2 entries:list for candidate 403, PERMISSION_DENIED, or exporter failures."""
    filter_expr = (
        f'timestamp >= "{since_rfc3339}" AND ('
        'protoPayload.status.code = 7 OR '
        'textPayload =~ "(PERMISSION_DENIED|SERVICE_DISABLED|403 Forbidden|Failed to export)" OR '
        'jsonPayload.message =~ "(PERMISSION_DENIED|SERVICE_DISABLED|403 Forbidden|Failed to export)"'
        ")"
    )
    body = json.dumps(
        {
            "resourceNames": [f"projects/{project_id}"],
            "filter": filter_expr,
            "orderBy": "timestamp desc",
            "pageSize": page_size,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://logging.googleapis.com/v2/entries:list",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-goog-user-project": project_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return list(data.get("entries") or [])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Cloud Logging query failed on {project_id}: HTTP {exc.code} {detail}") from exc


def _resolve_token(gcloud_config: str) -> str:
    """Reads an access token from gcloud using the requested configuration."""
    cmd = ["gcloud"]
    if gcloud_config:
        cmd.append(f"--configuration={gcloud_config}")
    cmd.extend(["auth", "print-access-token"])
    return subprocess.check_output(cmd, text=True).strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI flags for the Zero-Silent-403 Cloud Logging scanner."""
    parser = argparse.ArgumentParser(description="Scan GCP projects for silent background 403 / PERMISSION_DENIED log entries.")
    parser.add_argument("--projects", nargs="+", required=True, help="GCP project IDs to scan (e.g. hub inf sbx).")
    parser.add_argument("--since-minutes", type=int, default=60, help="Lookback window in minutes (default: 60).")
    parser.add_argument("--gcloud-config", default="", help="Optional gcloud configuration name (e.g. argolis).")
    parser.add_argument(
        "--allowlist",
        action="append",
        default=[],
        help="Additional substring marker for intentional negative security probes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Runs the Zero-Silent-403 audit across target projects and prints a JSON report."""
    args = parse_args(argv)
    since = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=args.since_minutes)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = _resolve_token(args.gcloud_config)
    allowlist = DEFAULT_INTENTIONAL_PROBE_EXCLUSIONS + tuple(args.allowlist)

    report: dict[str, Any] = {"since_utc": since, "projects": {}, "total_unexpected_denials": 0}
    for proj in args.projects:
        raw = fetch_project_denial_entries(proj, since, token)
        findings = classify_log_entries(raw, allowlist_substrings=allowlist)
        report["projects"][proj] = {
            "raw_candidate_entries": len(raw),
            "unexpected_denials": len(findings),
            "findings": findings,
        }
        report["total_unexpected_denials"] += len(findings)

    print(json.dumps(report, indent=2))
    return 0 if report["total_unexpected_denials"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
