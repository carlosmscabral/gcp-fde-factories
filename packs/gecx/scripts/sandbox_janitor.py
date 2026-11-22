#!/usr/bin/env python3
"""Hourly Sandbox Janitor for packs/gecx (Contract 4).

Deletes ephemeral CES apps whose displayName starts with '[CI]' and whose age exceeds
max_age_hours (default 4 hours). Runs strictly under the 7-permission gecxSandboxJanitor SA.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from typing import Any


def parse_rfc3339(ts: str) -> dt.datetime:
    """Parses an RFC 3339 timestamp returned by Google Cloud APIs into UTC datetime."""
    cleaned = ts.replace("Z", "+00:00")
    return dt.datetime.fromisoformat(cleaned).astimezone(dt.timezone.utc)


def select_expired_ci_apps(
    apps: list[dict[str, Any]], now_utc: dt.datetime, max_age_hours: float = 4.0, prefix: str = "[CI]"
) -> list[dict[str, Any]]:
    """Selects ephemeral apps matching prefix whose createTime exceeds max_age_hours."""
    cutoff = now_utc - dt.timedelta(hours=max_age_hours)
    expired: list[dict[str, Any]] = []
    for app in apps:
        display_name = str(app.get("displayName", ""))
        create_time = str(app.get("createTime", ""))
        if not display_name.startswith(prefix) or not create_time:
            continue
        if parse_rfc3339(create_time) <= cutoff:
            expired.append(app)
    return expired


def main(argv: list[str] | None = None) -> int:
    """Lists CES apps in Sandbox and deletes expired [CI] apps."""
    parser = argparse.ArgumentParser(description="Delete expired [CI] ephemeral CES apps.")
    parser.add_argument("--sandbox-project", required=True)
    parser.add_argument("--location", default="us")
    parser.add_argument("--max-age-hours", type=float, default=4.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cxas-bin", default="cxas")
    args = parser.parse_args(argv)

    token = os.environ.get("GECX_JANITOR_OAUTH_TOKEN", "")
    if not token:
        print("GECX_JANITOR_OAUTH_TOKEN is required.", file=sys.stderr)
        return 2

    url = f"https://ces.googleapis.com/v1beta/projects/{args.sandbox_project}/locations/{args.location}/apps"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": args.sandbox_project},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        apps = json.loads(resp.read().decode("utf-8")).get("apps", [])

    expired = select_expired_ci_apps(apps, dt.datetime.now(dt.timezone.utc), args.max_age_hours)
    print(f"Found {len(expired)} expired [CI] app(s) out of {len(apps)} total app(s).")

    for app in expired:
        name = str(app["name"])
        dn = str(app.get("displayName", ""))
        if args.dry_run:
            print(f"[DRY-RUN] Would delete {dn} ({name})")
            continue
        res = subprocess.run(
            [args.cxas_bin, "--no-input", "--oauth-token", token, "delete", "--app-name", name, "--force"],
            text=True,
            capture_output=True,
        )
        print(f"Deleted {dn} ({name}): rc={res.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
