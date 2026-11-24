#!/usr/bin/env python3
"""Thin CLI entrypoint that renders docs/hillclimbing-dashboard.html from docs/hillclimbing-runs.jsonl.

Keeps the repository HTML dashboard and the published Artifacts Service HTML identical
by generating output deterministically from the append-only JSONL ledger.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.hillclimbing_renderer import load_ledger, render_dashboard_html


def main() -> int:
    """Loads the Hillclimbing ledger and writes or verifies the HTML dashboard."""
    parser = argparse.ArgumentParser(
        description="Render docs/hillclimbing-dashboard.html deterministically from docs/hillclimbing-runs.jsonl."
    )
    parser.add_argument(
        "--ledger",
        default=str(REPO_ROOT / "docs/hillclimbing-runs.jsonl"),
        help="Path to the append-only Hillclimbing JSONL ledger.",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "docs/hillclimbing-dashboard.html"),
        help="Path to write the generated single-file HTML dashboard.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail with exit code 1 if the existing HTML differs from the ledger rendering.",
    )
    args = parser.parse_args()

    ledger_path = pathlib.Path(args.ledger).resolve()
    out_path = pathlib.Path(args.out).resolve()
    runs, digest = load_ledger(ledger_path)
    rendered = render_dashboard_html(runs, digest)

    if args.check:
        if not out_path.is_file() or out_path.read_text(encoding="utf-8") != rendered:
            print(
                f"DRIFT DETECTED: {out_path} is out of sync with {ledger_path}. "
                "Run: python3 scripts/render-hillclimbing-report.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {out_path} matches {ledger_path} (sha256:{digest[:16]}, {len(runs)} run(s)).")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"WROTE {out_path} from {ledger_path} ({len(runs)} run(s), sha256:{digest[:16]}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
