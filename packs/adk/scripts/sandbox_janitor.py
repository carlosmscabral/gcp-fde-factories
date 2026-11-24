#!/usr/bin/env python3
"""Hourly out-of-band Sandbox Janitor for packs/adk (Agent Engine + ephemeral Gemini Enterprise agents).

Runs exclusively under the dedicated Janitor SA (never registered on Scion Hub).
Selects only resources whose displayName starts with `[CI]` and whose age exceeds max_age_hours (default 4h).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def select_expired_ci_resources(
    resources: list[dict[str, Any]],
    now_utc: dt.datetime,
    max_age_hours: float = 4.0,
) -> list[str]:
    """Filters `[CI]`-prefixed ReasoningEngines or GE agents older than max_age_hours."""
    expired: list[str] = []
    cutoff = now_utc - dt.timedelta(hours=max_age_hours)
    for item in resources:
        display = str(item.get("displayName") or "")
        name = str(item.get("name") or "")
        created_raw = str(item.get("createTime") or "")
        if not (display.startswith("[CI]") and name and created_raw):
            continue
        try:
            created = dt.datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created <= cutoff:
            expired.append(name)
    return sorted(expired)


def _rest_call(method: str, url: str, token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated Vertex AI or Discovery Engine REST request."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": quota_project},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")}


def main(argv: list[str] | None = None) -> int:
    """Lists expired [CI] ReasoningEngines in Sandbox and deletes them when --apply is set."""
    parser = argparse.ArgumentParser(description="Clean up expired [CI] ADK Sandbox ReasoningEngines.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--max-age-hours", type=float, default=4.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("ADK_JANITOR_OAUTH_TOKEN", "")
    if not token:
        print("Missing ADK_JANITOR_OAUTH_TOKEN.", file=sys.stderr)
        return 1

    base = f"https://{args.region}-aiplatform.googleapis.com/v1beta1"
    st, body = _rest_call("GET", f"{base}/projects/{args.project}/locations/{args.region}/reasoningEngines", token, args.project)
    if st != 200:
        print(f"Failed to list reasoningEngines: HTTP {st}", file=sys.stderr)
        return 1

    targets = select_expired_ci_resources(
        body.get("reasoningEngines", []), dt.datetime.now(dt.timezone.utc), args.max_age_hours
    )
    deleted: list[str] = []
    for res_name in targets:
        if args.apply:
            d_st, _ = _rest_call("DELETE", f"{base}/{res_name}", token, args.project)
            if 200 <= d_st < 300:
                deleted.append(res_name)
    print(json.dumps({"expired_found": targets, "deleted": deleted, "dry_run": not args.apply}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
