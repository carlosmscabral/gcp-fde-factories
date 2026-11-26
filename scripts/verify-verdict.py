#!/usr/bin/env python3
"""Thin CLI wrapper invoking scripts.lib.verdict_checker for GitHub Actions Verdict Gates."""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
for candidate in (str(SCRIPT_DIR), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from scripts.lib.verdict_checker import verify_verdict


def default_verdict_schema() -> pathlib.Path:
    """Resolves verdict.schema.json inside either the source repo or container /opt/gcp-fde layout."""
    for cand in (
        SCRIPT_DIR / "schemas" / "verdict.schema.json",
        REPO_ROOT / "schemas" / "verdict.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/verdict.schema.json"),
    ):
        if cand.is_file():
            return cand
    return REPO_ROOT / "schemas" / "verdict.schema.json"


def main(argv: list[str] | None = None) -> int:
    """Validates a PR Verdict JSON against schema, commit SHA, evals hash, and live Sandbox APIs."""
    parser = argparse.ArgumentParser(description="Verify PR Verdict provenance.")
    parser.add_argument("--verdict", required=True, type=pathlib.Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evals-dir", required=True, type=pathlib.Path)
    parser.add_argument("--sandbox-project", default="")
    parser.add_argument("--sandbox-project-number", default=os.environ.get("SANDBOX_PROJECT_NUMBER", ""))
    parser.add_argument("--expected-evaluator-sa", default="")
    parser.add_argument("--expected-pack", default="")
    parser.add_argument("--expected-pr-number", type=int, default=None)
    parser.add_argument("--allowed-surfaces", default="")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--schema", type=pathlib.Path, default=default_verdict_schema())
    args = parser.parse_args(argv)

    allowed = {s.strip() for s in args.allowed_surfaces.split(",") if s.strip()} if args.allowed_surfaces else None
    errors = verify_verdict(
        verdict_path=args.verdict,
        schema_path=args.schema,
        expected_commit=args.expected_commit,
        evals_dir=args.evals_dir,
        sandbox_project=args.sandbox_project,
        expected_evaluator_sa=args.expected_evaluator_sa,
        access_token=os.environ.get("EVAL_ACCESS_TOKEN", ""),
        expected_pack=args.expected_pack,
        expected_pr_number=args.expected_pr_number,
        allowed_surfaces=allowed,
        require_live=args.require_live,
        sandbox_project_number=args.sandbox_project_number,
    )
    if errors:
        for err in errors:
            print(f"VERDICT FAIL: {err}", file=sys.stderr)
        return 1
    print("VERDICT PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
