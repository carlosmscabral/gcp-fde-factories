#!/usr/bin/env python3
"""Thin CLI composition root for the 0-token Kaizen telemetry collector (v0.3.0).

Packaged into /opt/gcp-fde/kaizen_collect.py inside core-gcp-fde/images/base.Dockerfile.
Delegates all collection and schema validation logic to scripts/lib/kaizen_collector.py.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent.parent if (SCRIPT_ROOT.parent.parent / "scripts" / "lib").exists() else SCRIPT_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.kaizen_collector import build_kaizen_snapshot, write_validated_snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI arguments for the Kaizen snapshot collector."""
    parser = argparse.ArgumentParser(description="Collect 0-token factory telemetry for Kaizen analysis.")
    parser.add_argument("--hub-url", default=os.environ.get("SCION_HUB_ENDPOINT", ""))
    parser.add_argument("--project-id", default=os.environ.get("SCION_PROJECT_ID", ""))
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--scratchpad", type=pathlib.Path, default=pathlib.Path("/scion-volumes/scratchpad"))
    parser.add_argument("--workarounds", type=pathlib.Path, default=None)
    parser.add_argument("--toolchain-manifest", type=pathlib.Path, default=None)
    parser.add_argument("--skip-drift", action="store_true")
    parser.add_argument("--enable-gcp-obs", action="store_true")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        default=REPO_ROOT / "schemas" / "kaizen-snapshot.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Collects telemetry, validates against schema, and writes the snapshot JSON."""
    args = parse_args(argv)
    agent_token = os.environ.get("SCION_AUTH_TOKEN") or os.environ.get("SCION_HUB_TOKEN") or ""
    workarounds = args.workarounds
    if workarounds is None and (args.repo / "WORKAROUNDS.yaml").exists():
        workarounds = args.repo / "WORKAROUNDS.yaml"

    snapshot = build_kaizen_snapshot(
        hub_url=args.hub_url,
        project_id=args.project_id,
        agent_token=agent_token,
        repo_dir=args.repo,
        scratchpad_dir=args.scratchpad,
        workarounds_path=workarounds,
        toolchain_manifest=args.toolchain_manifest,
        include_drift=not args.skip_drift,
        enable_gcp_obs=args.enable_gcp_obs,
    )
    errors = write_validated_snapshot(snapshot, args.out, args.schema)
    if errors:
        for err in errors:
            print(f"SNAPSHOT SCHEMA ERROR: {err}", file=sys.stderr)
        return 1
    print(f"KAIZEN SNAPSHOT READY: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
