#!/usr/bin/env python3
"""Thin CLI wrapper invoking scripts.lib.verdict_checker for GitHub Actions Verdict Gate."""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.verdict_checker import verify_verdict


def main() -> int:
    """Validates a PR Verdict JSON against schema, commit SHA, evals hash, and live CES API."""
    parser = argparse.ArgumentParser(description="Verify PR Verdict provenance.")
    parser.add_argument("--verdict", required=True, type=pathlib.Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evals-dir", required=True, type=pathlib.Path)
    parser.add_argument("--sandbox-project", default="")
    parser.add_argument("--expected-evaluator-sa", default="")
    parser.add_argument("--schema", type=pathlib.Path, default=REPO_ROOT / "schemas" / "verdict.schema.json")
    args = parser.parse_args()

    errors = verify_verdict(
        verdict_path=args.verdict,
        schema_path=args.schema,
        expected_commit=args.expected_commit,
        evals_dir=args.evals_dir,
        sandbox_project=args.sandbox_project,
        expected_evaluator_sa=args.expected_evaluator_sa,
        access_token=os.environ.get("EVAL_ACCESS_TOKEN", ""),
    )
    if errors:
        for err in errors:
            print(f"VERDICT FAIL: {err}", file=sys.stderr)
        return 1
    print("VERDICT PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
