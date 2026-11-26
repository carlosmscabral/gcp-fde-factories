#!/usr/bin/env python3
"""Ephemeral [CI] Cloud Run Sandbox Janitor for packs/generic (INV-08, HC06-F1 pattern).

Deletes ONLY expired Cloud Run services in the disposable Sandbox project carrying the
factory_ci=true label or ci-pr- name prefix. Never mutates non-CI customer services.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from typing import Any


def parse_rfc3339(raw: str) -> dt.datetime:
    """Parses an RFC-3339 UTC timestamp string into an aware datetime."""
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def select_expired_ci_services(
    services: list[dict[str, Any]],
    *,
    ttl_hours: float,
    now_utc: dt.datetime | None = None,
) -> list[dict[str, str]]:
    """Selects only expired services labeled factory_ci=true or prefixed ci-pr-."""
    ref_now = now_utc or dt.datetime.now(dt.timezone.utc)
    cutoff = ref_now - dt.timedelta(hours=ttl_hours)
    expired: list[dict[str, str]] = []

    for svc in services:
        meta = svc.get("metadata") if isinstance(svc.get("metadata"), dict) else {}
        name = str(meta.get("name") or svc.get("name") or "").split("/")[-1]
        labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else (svc.get("labels") or {})
        is_ci = str(labels.get("factory_ci", "")).lower() == "true" or name.startswith("ci-pr-")
        if not name or not is_ci:
            continue
        ts_raw = str(meta.get("creationTimestamp") or svc.get("createTime") or "")
        if not ts_raw:
            continue
        try:
            created = parse_rfc3339(ts_raw)
        except ValueError:
            continue
        if created <= cutoff:
            expired.append({"name": name, "created_at": ts_raw})
    return expired


def sweep_cloud_run_sandbox(
    project: str,
    region: str,
    *,
    ttl_hours: float = 4.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Lists Cloud Run services in Sandbox and deletes expired ephemeral CI services."""
    list_cmd = [
        "gcloud", "run", "services", "list",
        f"--project={project}", f"--region={region}", "--format=json",
    ]
    proc = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip(), "deleted": [], "dry_run": dry_run}
    services = json.loads(proc.stdout or "[]")
    targets = select_expired_ci_services(services, ttl_hours=ttl_hours)
    deleted: list[str] = []
    errors: list[str] = []

    for item in targets:
        svc_name = item["name"]
        if dry_run:
            deleted.append(svc_name)
            continue
        del_cmd = [
            "gcloud", "run", "services", "delete", svc_name,
            f"--project={project}", f"--region={region}", "--quiet",
        ]
        res = subprocess.run(del_cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            deleted.append(svc_name)
        else:
            errors.append(f"{svc_name}: {res.stderr.strip()}")
    return {"ok": len(errors) == 0, "project": project, "region": region, "dry_run": dry_run, "deleted": deleted, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    """Parses CLI arguments and runs ephemeral Cloud Run Sandbox cleanup."""
    parser = argparse.ArgumentParser(description="Sweep expired [CI] / factory_ci=true Cloud Run Sandbox services.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--ttl-hours", type=float, default=4.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = sweep_cloud_run_sandbox(args.project, args.region, ttl_hours=args.ttl_hours, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
