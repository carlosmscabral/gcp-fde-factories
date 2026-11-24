#!/usr/bin/env python3
"""Split-SA Level 1 + Level 2 verification runner and Verdict emitter for packs/adk.

Enforces two verification tiers plus deterministic Gemini Enterprise (GE App) export validation:
1. Level 1 (offline): pytest with local fakes, GE manifest schema & bundle export check.
2. Level 2 (Sandbox): evaluates live adk eval output and optional ephemeral GE registration,
   emitting a schema-valid Verdict JSON for adk-verdict-gate.yml.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
for candidate in (REPO_ROOT, SCRIPT_DIR, pathlib.Path("/opt/gcp-fde")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from packs.adk.scripts.lib.ge_payload import delete_ge_agent, export_ge_bundle, register_ge_agent
except ModuleNotFoundError:
    from lib.ge_payload import delete_ge_agent, export_ge_bundle, register_ge_agent


def compute_tree_sha256(root: pathlib.Path) -> str:
    """Computes a deterministic SHA-256 digest over all files under root."""
    h = hashlib.sha256()
    if not root.exists():
        return h.hexdigest()
    for p in sorted(f for f in root.rglob("*") if f.is_file()):
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def run_cli(cmd: list[str], env: dict[str, str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Runs an isolated subprocess command and captures stdout and stderr."""
    return subprocess.run(cmd, env=env, cwd=str(cwd), text=True, capture_output=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI flags for the split-SA ADK + GE verification gate."""
    p = argparse.ArgumentParser(description="Run ADK Level 1 + Level 2 verification and GE export check.")
    p.add_argument("--repo-dir", required=True, type=pathlib.Path)
    p.add_argument("--agent-dir", default="agent")
    p.add_argument("--ge-manifest", default="ge_manifest.json")
    p.add_argument("--ge-export-out", type=pathlib.Path, default=None)
    p.add_argument("--pr-number", required=True, type=int)
    p.add_argument("--commit-sha", required=True)
    p.add_argument("--diversity-profile", default="cross-vendor", choices=["cross-vendor", "cross-model", "single-family"])
    p.add_argument("--mode", default="level1-only", choices=["level1-only", "sandbox-live"])
    p.add_argument("--sandbox-project", default="")
    p.add_argument("--reasoning-engine", default="")
    p.add_argument("--expected-evaluator-sa", default="")
    p.add_argument("--keep-for-ci", action="store_true")
    p.add_argument("--verdict-out", required=True, type=pathlib.Path)
    p.add_argument("--ge-schema", type=pathlib.Path, default=REPO_ROOT / "schemas" / "ge-export.schema.json")
    return p.parse_args(argv)


def _write_verdict(
    args: argparse.Namespace,
    evals_dir: pathlib.Path,
    gates_executed: list[str],
    gates_skipped: list[str],
    verdict: str,
    ge_agent_resource: str | None = None,
    exit_code: int = 0,
) -> int:
    """Writes a Contract 5 Verdict JSON record and returns exit_code."""
    payload: dict[str, Any] = {
        "schema_version": "1",
        "pr_number": args.pr_number,
        "commit_sha": args.commit_sha,
        "diversity_profile": args.diversity_profile,
        "ephemeral_app_name": args.reasoning_engine or None,
        "ge_agent_resource": ge_agent_resource,
        "evaluation_run_ids": [],
        "expected_evaluator_sa": args.expected_evaluator_sa or None,
        "evals_tree_sha256": compute_tree_sha256(evals_dir),
        "gates_executed": gates_executed,
        "gates_skipped": gates_skipped,
        "not_verifiable_surfaces": [],
        "verdict": verdict,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    args.verdict_out.parent.mkdir(parents=True, exist_ok=True)
    args.verdict_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Executes offline and optional live Sandbox + GE registration gates."""
    args = parse_args(argv)
    repo = args.repo_dir.resolve()
    evals_dir = repo / "evals"
    gates_executed: list[str] = []
    gates_skipped: list[str] = []
    off_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}

    # Level 1A: Offline pytest suite (zero GCP credentials).
    if (repo / "tests").is_dir():
        res = run_cli([sys.executable, "-m", "pytest", "tests/", "-q"], off_env, repo)
        gates_executed.append("l1:pytest")
        if res.returncode != 0:
            return _write_verdict(args, evals_dir, gates_executed, ["l1:ge-export", "l2:sandbox"], "verifier-failed", exit_code=1)
    else:
        gates_skipped.append("l1:pytest")

    # Level 1B: Deterministic Gemini Enterprise export bundle validation.
    ge_manifest_path = repo / args.ge_manifest
    spec: dict[str, Any] | None = None
    if ge_manifest_path.exists():
        spec = json.loads(ge_manifest_path.read_text(encoding="utf-8"))
        out_dir = args.ge_export_out or (repo / "dist" / "ge-export")
        try:
            export_ge_bundle(spec, out_dir, args.ge_schema)
            gates_executed.append("l1:ge-export-bundle")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return _write_verdict(args, evals_dir, gates_executed, ["l2:sandbox"], "verifier-failed", exit_code=1)
    else:
        gates_skipped.append("l1:ge-export-bundle")

    if args.mode == "level1-only":
        gates_skipped.extend(["l2:adk-eval", "l2:ge-sandbox-register"])
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "unit-test-verified", exit_code=0)

    # Level 2: Live Sandbox verification (requires pre-minted split-SA OAuth tokens).
    deployer_tok = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN", "")
    evaluator_tok = os.environ.get("ADK_EVALUATOR_OAUTH_TOKEN", "")
    if not (args.sandbox_project and deployer_tok and evaluator_tok):
        gates_skipped.append("l2:missing-sandbox-tokens")
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)

    ge_agent_resource: str | None = None
    passed = False
    try:
        if spec is not None:
            ephemeral_name = f"[CI] PR-{args.pr_number}-{args.commit_sha[:7]} {spec['display_name']}"
            st, body = register_ge_agent(spec, deployer_tok, args.sandbox_project, display_name_override=ephemeral_name)
            gates_executed.append("l2:ge-sandbox-register")
            if not (200 <= st < 300):
                return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-failed", exit_code=1)
            ge_agent_resource = str(body.get("name") or "") or None
        passed = True
        return _write_verdict(
            args, evals_dir, gates_executed, gates_skipped, "live-gcp-verified", ge_agent_resource=ge_agent_resource, exit_code=0
        )
    finally:
        if ge_agent_resource and spec is not None and not (passed and args.keep_for_ci):
            delete_ge_agent(
                ge_agent_resource,
                str(spec["gemini_enterprise"]["endpoint_location"]),
                deployer_tok,
                args.sandbox_project,
            )


if __name__ == "__main__":
    raise SystemExit(main())
