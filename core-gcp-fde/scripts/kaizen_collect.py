#!/usr/bin/env python3
"""Thin CLI composition root for the 0-token Kaizen telemetry collector (v0.3.0).

Packaged into /opt/gcp-fde/kaizen_collect.py inside core-gcp-fde/images/base.Dockerfile.
Delegates all collection and schema validation logic to scripts/lib/kaizen_collector.py.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent.parent if (SCRIPT_ROOT.parent.parent / "scripts" / "lib").exists() else SCRIPT_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.kaizen_collector import build_kaizen_snapshot, write_validated_snapshot
from scripts.lib.kaizen_sources import resolve_hub_auth_header


def _default_workarounds(repo: pathlib.Path) -> pathlib.Path | None:
    """Resolves WORKAROUNDS.yaml from target repo or packaged /opt/gcp-fde."""
    for cand in (repo / "WORKAROUNDS.yaml", pathlib.Path("/opt/gcp-fde/WORKAROUNDS.yaml")):
        if cand.is_file():
            return cand
    return None


def _default_toolchain_manifest() -> pathlib.Path | None:
    """Resolves a packaged pack toolchain manifest inside /opt/gcp-fde when omitted."""
    opt_dir = pathlib.Path("/opt/gcp-fde")
    if opt_dir.is_dir():
        matches = sorted(opt_dir.glob("*-toolchain-manifest.json"))
        if matches:
            return matches[0]
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI arguments for the Kaizen snapshot collector."""
    parser = argparse.ArgumentParser(description="Collect 0-token factory telemetry for Kaizen analysis.")
    parser.add_argument("--hub-url", default=os.environ.get("SCION_HUB_ENDPOINT", ""))
    parser.add_argument("--project-id", default=os.environ.get("SCION_PROJECT_ID", ""))
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--scratchpad", type=pathlib.Path, default=pathlib.Path("/scion-volumes/scratchpad"))
    parser.add_argument("--verdicts-dir", type=pathlib.Path, default=None)
    parser.add_argument("--workarounds", type=pathlib.Path, default=None)
    parser.add_argument("--proposals", type=pathlib.Path, default=None)
    parser.add_argument("--history-dir", type=pathlib.Path, default=None)
    parser.add_argument("--no-history", action="store_true", help="Disable dated snapshot archiving.")
    parser.add_argument("--toolchain-manifest", type=pathlib.Path, default=None)
    parser.add_argument("--time-zone", default="America/Sao_Paulo")
    parser.add_argument("--skip-drift", action="store_true")
    parser.add_argument("--enable-gcp-obs", action="store_true")
    parser.add_argument(
        "--gcp-obs-json",
        type=pathlib.Path,
        default=None,
        help="Path to a pre-fetched Cloud Monitoring/Logging JSON summary object.",
    )
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--schema", type=pathlib.Path, default=REPO_ROOT / "schemas" / "kaizen-snapshot.schema.json")
    return parser.parse_args(argv)


def _load_gcp_obs_payload(obs_path: pathlib.Path | None) -> tuple[dict[str, object] | None, str | None]:
    """Reads an optional pre-fetched Cloud Monitoring/Logging JSON summary."""
    if obs_path is None:
        return None, None
    try:
        raw = json.loads(obs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"gcp_observability: unreadable --gcp-obs-json '{obs_path}': {exc}"
    if not isinstance(raw, dict):
        return None, f"gcp_observability: --gcp-obs-json '{obs_path}' must contain a JSON object."
    return raw, None


def main(argv: list[str] | None = None) -> int:
    """Collects telemetry, validates against schema, and writes the snapshot JSON."""
    args = parse_args(argv)
    resolved_history = None if args.no_history else (args.history_dir or (args.repo / ".factory" / "kaizen" / "snapshots"))
    obs_payload, obs_err = _load_gcp_obs_payload(args.gcp_obs_json)
    snapshot = build_kaizen_snapshot(
        hub_url=args.hub_url,
        project_id=args.project_id,
        auth_headers=resolve_hub_auth_header(),
        repo_dir=args.repo,
        scratchpad_dir=args.scratchpad,
        verdicts_dir=args.verdicts_dir,
        workarounds_path=args.workarounds or _default_workarounds(args.repo),
        proposals_path=args.proposals,
        history_dir=resolved_history,
        toolchain_manifest=args.toolchain_manifest or _default_toolchain_manifest(),
        include_drift=not args.skip_drift,
        enable_gcp_obs=bool(args.enable_gcp_obs or args.gcp_obs_json is not None),
        gcp_obs_payload=obs_payload,
        time_zone=args.time_zone,
    )
    if obs_err:
        snapshot["source_errors"].append(obs_err[:240])
    state_path = (args.proposals.parent / "proposals.state.json") if args.proposals else (args.repo / ".factory" / "kaizen" / "proposals.state.json")
    errors = write_validated_snapshot(
        snapshot,
        args.out,
        args.schema,
        history_dir=resolved_history,
        proposal_state_path=state_path if snapshot.get("proposal_verifications") else None,
    )
    if errors:
        for err in errors:
            print(f"SNAPSHOT SCHEMA ERROR: {err}", file=sys.stderr)
        return 1
    print(f"KAIZEN SNAPSHOT READY: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
