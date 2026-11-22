#!/usr/bin/env python3
"""Thin CLI wrapper invoking scripts.lib.budget_engine for total context and TTL checks."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.budget_engine import check_context_budget, check_workarounds_ttl


def main() -> int:
    """Runs context budget (Layers 0+1+2) and WORKAROUNDS.yaml TTL validation."""
    parser = argparse.ArgumentParser(description="Validate total context budgets and workaround TTLs.")
    parser.add_argument("--pack", default="packs/gecx")
    parser.add_argument("--overlay", type=pathlib.Path, default=None)
    args = parser.parse_args()

    errors, report = check_context_budget(REPO_ROOT, REPO_ROOT / args.pack, args.overlay)
    errors.extend(check_workarounds_ttl(REPO_ROOT / "WORKAROUNDS.yaml"))
    print(json.dumps(report, indent=2))
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
