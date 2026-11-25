#!/usr/bin/env python3
"""Hourly out-of-band Sandbox Janitor for packs/adk (ReasoningEngines, Cloud Run, and GE agents).

Runs exclusively under the dedicated Janitor SA (never registered on Scion Hub).
Paginates all resources, selects only `[CI]`-prefixed Vertex AI / GE resources and
`factory_ci=true`-labeled Cloud Run services older than max_age_hours (4h), deletes
them without touching non-CI customer workloads, and exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

RestFn = Callable[[str, str, str, str], tuple[int, dict[str, Any]]]


def select_expired_ci_resources(
    resources: list[dict[str, Any]],
    now_utc: dt.datetime,
    max_age_hours: float = 4.0,
    skip_resources: set[str] | None = None,
) -> list[str]:
    """Filters `[CI]`-prefixed ReasoningEngines or GE agents older than max_age_hours."""
    expired: list[str] = []
    skipped = skip_resources or set()
    cutoff = now_utc - dt.timedelta(hours=max_age_hours)
    for item in resources:
        display = str(item.get("displayName") or "")
        name = str(item.get("name") or "")
        # Use updateTime when present so shared PATCH-reused Sandbox GE agents stay alive while active.
        ts_raw = str(item.get("updateTime") or item.get("createTime") or "")
        if not (display.startswith("[CI]") and name and ts_raw) or name in skipped:
            continue
        try:
            ref_time = dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=dt.timezone.utc)
        if ref_time <= cutoff:
            expired.append(name)
    return sorted(expired)


def select_expired_ci_cloud_run_services(
    services: list[dict[str, Any]],
    now_utc: dt.datetime,
    max_age_hours: float = 4.0,
) -> list[str]:
    """Filters Cloud Run v2 services labeled factory_ci=true older than max_age_hours (HC-06 F1)."""
    expired: list[str] = []
    cutoff = now_utc - dt.timedelta(hours=max_age_hours)
    for item in services:
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        name = str(item.get("name") or "")
        # Cloud Run v2 uses updateTime/createTime; skip any service lacking factory_ci=true to protect customer apps.
        ts_raw = str(item.get("updateTime") or item.get("createTime") or "")
        if not (str(labels.get("factory_ci", "")).lower() == "true" and name and ts_raw):
            continue
        try:
            ref_time = dt.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=dt.timezone.utc)
        if ref_time <= cutoff:
            expired.append(name)
    return sorted(expired)


def default_rest_call(method: str, url: str, token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
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
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return 0, {"error": str(exc)}


def _list_paginated(
    base_url: str,
    items_key: str,
    token: str,
    quota_project: str,
    rest_fn: RestFn,
) -> tuple[bool, list[dict[str, Any]], str]:
    """Lists all pages of a Google Cloud REST collection using nextPageToken."""
    all_items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}pageToken={urllib.parse.quote(page_token)}" if page_token else base_url
        st, body = rest_fn("GET", url, token, quota_project)
        if st != 200:
            return False, all_items, f"GET {url} failed with HTTP {st}"
        all_items.extend(body.get(items_key, []) or [])
        page_token = str(body.get("nextPageToken") or "")
        if not page_token:
            return True, all_items, ""


def run_janitor(
    project: str,
    regions: list[str],
    token: str,
    max_age_hours: float = 4.0,
    apply: bool = False,
    ge_app: str = "",
    ge_location: str = "global",
    ge_assistant: str = "default_assistant",
    skip_resources: set[str] | None = None,
    now_utc: dt.datetime | None = None,
    rest_fn: RestFn = default_rest_call,
) -> tuple[int, dict[str, Any]]:
    """Sweeps expired [CI] ReasoningEngines and optional Gemini Enterprise agents."""
    ref_now = now_utc or dt.datetime.now(dt.timezone.utc)
    found: list[str] = []
    deleted: list[str] = []
    failures: list[str] = []

    for region in regions:
        base = f"https://{region}-aiplatform.googleapis.com/v1beta1"
        ok, engines, err = _list_paginated(
            f"{base}/projects/{project}/locations/{region}/reasoningEngines",
            "reasoningEngines",
            token,
            project,
            rest_fn,
        )
        if not ok:
            failures.append(err)
        else:
            expired = select_expired_ci_resources(engines, ref_now, max_age_hours)
            found.extend(expired)
            if apply:
                for name in expired:
                    st, _ = rest_fn("DELETE", f"{base}/{name}?force=true", token, project)
                    if 200 <= st < 300:
                        deleted.append(name)
                    else:
                        failures.append(f"DELETE {name} failed with HTTP {st}")

        # Sweep orphaned ephemeral Cloud Run v2 services labeled factory_ci=true (HC-06 F1).
        cr_base = "https://run.googleapis.com/v2"
        ok_cr, cr_services, err_cr = _list_paginated(
            f"{cr_base}/projects/{project}/locations/{region}/services",
            "services",
            token,
            project,
            rest_fn,
        )
        if not ok_cr:
            failures.append(err_cr)
        else:
            expired_cr = select_expired_ci_cloud_run_services(cr_services, ref_now, max_age_hours)
            found.extend(expired_cr)
            if apply:
                for name in expired_cr:
                    st, _ = rest_fn("DELETE", f"{cr_base}/{name}", token, project)
                    if 200 <= st < 300:
                        deleted.append(name)
                    else:
                        failures.append(f"DELETE {name} failed with HTTP {st}")

    if ge_app:
        prefix = "" if ge_location == "global" else f"{ge_location}-"
        ge_base = f"https://{prefix}discoveryengine.googleapis.com/v1alpha"
        ge_list_url = (
            f"{ge_base}/projects/{project}/locations/{ge_location}/collections/default_collection/"
            f"engines/{ge_app}/assistants/{ge_assistant}/agents"
        )
        ok, agents, err = _list_paginated(ge_list_url, "agents", token, project, rest_fn)
        if not ok:
            failures.append(err)
        else:
            expired_ge = select_expired_ci_resources(agents, ref_now, max_age_hours, skip_resources=skip_resources)
            found.extend(expired_ge)
            if apply:
                for name in expired_ge:
                    st, _ = rest_fn("DELETE", f"{ge_base}/{name}", token, project)
                    if 200 <= st < 300:
                        deleted.append(name)
                    else:
                        failures.append(f"DELETE {name} failed with HTTP {st}")

    report = {"expired_found": sorted(found), "deleted": sorted(deleted), "failures": failures, "dry_run": not apply}
    return (0 if not failures else 1), report


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for sweeping expired [CI] ReasoningEngines and GE agents."""
    parser = argparse.ArgumentParser(description="Clean up expired [CI] ADK Sandbox ReasoningEngines and GE agents.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--regions", default="us-central1", help="Comma-separated Vertex AI regions.")
    parser.add_argument("--ge-app", default="", help="Optional Gemini Enterprise Sandbox app_id to sweep.")
    parser.add_argument("--ge-location", default="global", choices=["global", "us", "eu"])
    parser.add_argument("--assistant", default="default_assistant")
    parser.add_argument("--skip-ge-agent", action="append", default=[], help="GE agent resource name to preserve (e.g. shared PATCH target).")
    parser.add_argument("--max-age-hours", type=float, default=4.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("ADK_JANITOR_OAUTH_TOKEN", "").strip()
    if not token:
        print("Missing ADK_JANITOR_OAUTH_TOKEN.", file=sys.stderr)
        return 1

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    rc, report = run_janitor(
        project=args.project,
        regions=regions,
        token=token,
        max_age_hours=args.max_age_hours,
        apply=args.apply,
        ge_app=args.ge_app,
        ge_location=args.ge_location,
        ge_assistant=args.assistant,
        skip_resources=set(args.skip_ge_agent),
    )
    print(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
