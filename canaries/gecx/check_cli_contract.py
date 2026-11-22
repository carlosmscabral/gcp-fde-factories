#!/usr/bin/env python3
"""Verifies that the installed `cxas` CLI preserves all flags captured in the canary snapshot.

Blocks drift PRs when an upstream cxas-scrapi release renames or drops required CLI flags.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

REQUIRED_FLAGS: dict[str, list[str]] = {
    "lint": ["--app-dir"],
    "push": ["--app-dir", "--project-id", "--location", "--display-name"],
    "push-eval": ["--app-name", "--file"],
    "test-callbacks": ["--app-dir"],
    "test-tools": ["--app-name", "--test-file"],
    "run": ["--app-name", "--eval-type", "--wait"],
    "delete": ["--app-name", "--force"],
}


def check_contract_snapshot(snapshot_path: pathlib.Path) -> list[str]:
    """Validates that the versioned CLI contract snapshot covers every required flag."""
    snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for subcmd, flags in REQUIRED_FLAGS.items():
        help_text = str(snap.get(subcmd, {}).get("help") or snap.get(subcmd, {}).get("out", ""))
        for flag in flags:
            if flag not in help_text:
                errors.append(f"Snapshot missing flag '{flag}' for 'cxas {subcmd}'.")
    return errors


def check_live_cli(cxas_bin: str) -> list[str]:
    """Invokes `<cxas_bin> <subcmd> --help` live and verifies every required flag exists."""
    errors: list[str] = []
    for subcmd, flags in REQUIRED_FLAGS.items():
        res = subprocess.run([cxas_bin, subcmd, "--help"], text=True, capture_output=True)
        combined = res.stdout + res.stderr
        if res.returncode != 0:
            errors.append(f"'{cxas_bin} {subcmd} --help' exited {res.returncode}.")
            continue
        for flag in flags:
            if flag not in combined:
                errors.append(f"Live CLI missing flag '{flag}' for 'cxas {subcmd}'.")
    return errors


def main() -> int:
    """Runs snapshot validation and optional live CLI validation."""
    parser = argparse.ArgumentParser(description="Validate cxas CLI contract flags.")
    parser.add_argument(
        "--snapshot",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent / "cxas_1.11.0_cli_contract.json",
    )
    parser.add_argument("--live-cxas", default="", help="Optional path to live cxas binary.")
    args = parser.parse_args()

    errors = check_contract_snapshot(args.snapshot)
    if args.live_cxas:
        errors.extend(check_live_cli(args.live_cxas))
    if errors:
        for err in errors:
            print(f"CLI CONTRACT FAIL: {err}", file=sys.stderr)
        return 1
    print("CLI CONTRACT PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
