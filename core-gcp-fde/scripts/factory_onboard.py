#!/usr/bin/env python3
"""Thin CLI composition root for Day-0 brownfield onboarding and Day-2 drift detection (v0.4.0).

Inspired by scion-defaults: owns deterministic repository scanning, Readiness Gate validation,
and atomic non-destructive Layer 3 overlay emission. Always emits JSON and returns exit 1 on errors.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent.parent if (SCRIPT_ROOT.parent.parent / "scripts" / "lib").exists() else SCRIPT_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.dockerfile_recipes import validate_customer_dockerfile
from scripts.lib.io_utils import load_yaml
from scripts.lib.onboard_emitter import check_readiness, emit_layer3_overlay
from scripts.lib.onboard_scanner import detect_repo_drift, scan_repository_facts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses scan, check, and emit subcommands (including --json for spec compatibility)."""
    parser = argparse.ArgumentParser(description="Static scanner, Readiness Gate, and Layer 3 overlay emitter.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--repo", type=pathlib.Path, required=True)
    p_scan.add_argument("--toolchain-manifest", type=pathlib.Path, default=None)
    p_scan.add_argument("--drift", action="store_true")
    p_scan.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_scan.add_argument("--out", type=pathlib.Path, default=None)

    p_check = sub.add_parser("check")
    p_check.add_argument("--profile", type=pathlib.Path, required=True)
    p_check.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_check.add_argument(
        "--schema",
        type=pathlib.Path,
        default=REPO_ROOT / "schemas" / "factory-profile.schema.json",
    )

    p_emit = sub.add_parser("emit")
    p_emit.add_argument("--repo", type=pathlib.Path, required=True)
    p_emit.add_argument("--profile", type=pathlib.Path, required=True)
    p_emit.add_argument("--pack-image", required=True)
    p_emit.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    p_emit.add_argument(
        "--schema",
        type=pathlib.Path,
        default=REPO_ROOT / "schemas" / "factory-profile.schema.json",
    )
    p_val = sub.add_parser("validate-dockerfile")
    p_val.add_argument("--dockerfile", type=pathlib.Path, required=True)
    p_val.add_argument("--strict", action="store_true", help="Fail closed on advisory security findings.")
    p_val.add_argument("--json", action="store_true", help="Emit JSON output (default behavior).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatches scan, Readiness Gate check, emit, or Dockerfile contract validation."""
    args = parse_args(argv)
    try:
        if args.cmd == "validate-dockerfile":
            report = validate_customer_dockerfile(args.dockerfile, strict=args.strict)
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1

        if args.cmd == "scan":
            if not args.repo.is_dir():
                raise ValueError(f"Repository directory does not exist: {args.repo}")
            payload = (
                detect_repo_drift(args.repo, args.toolchain_manifest)
                if args.drift
                else scan_repository_facts(args.repo, args.toolchain_manifest)
            )
            encoded = json.dumps(payload, indent=2) + "\n"
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(encoded, encoding="utf-8")
            else:
                print(encoded, end="")
            return 0

        profile = load_yaml(args.profile)
        if not isinstance(profile, dict):
            raise ValueError(f"Profile must be a YAML mapping: {args.profile}")

        if args.cmd == "check":
            report = check_readiness(profile, args.schema)
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1

        result = emit_layer3_overlay(args.repo, profile, args.pack_image, args.schema)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
