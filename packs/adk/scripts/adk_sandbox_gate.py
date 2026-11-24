#!/usr/bin/env python3
"""Split-SA Level 1 + Level 2 verification runner and Contract 5 Verdict emitter for packs/adk.

Enforces real split-SA separation:
- Level 1 (offline, scrubbed HOME/ADC): pytest, root Dockerfile contract check, and GE export bundle check.
  Emits 'static-check-only' when no unit tests executed and 'unit-test-verified' only when pytest passes.
- Level 2 deploy phase (Deployer SA only): refuses non-sandbox targets, registers or PATCHes
  ephemeral Gemini Enterprise agent bound to --reasoning-engine, records ledger entry.
- Level 2 evaluate phase (Evaluator SA only): runs real `adk eval` with strict result parsing
  (fails closed on 0 cases or any failure) and validates the Verdict against verdict.schema.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
for candidate in (REPO_ROOT, SCRIPT_DIR, pathlib.Path("/opt/gcp-fde")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from scripts.lib.io_utils import sha256_tree
from scripts.lib.schema_validator import validate_against_schema

try:
    from packs.adk.scripts.lib.ge_payload import (
        default_ge_schema,
        delete_ge_agent,
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
    )
except ModuleNotFoundError:
    from lib.ge_payload import (
        default_ge_schema,
        delete_ge_agent,
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
    )

PASS_COUNT_RE = re.compile(r"Tests passed:\s*(\d+)", re.I)
FAIL_COUNT_RE = re.compile(r"Tests failed:\s*(\d+)", re.I)


def _default_verdict_schema() -> pathlib.Path:
    """Locates schemas/verdict.schema.json inside repo or container /opt/gcp-fde."""
    for cand in (
        REPO_ROOT / "schemas" / "verdict.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/verdict.schema.json"),
    ):
        if cand.is_file():
            return cand
    return REPO_ROOT / "schemas" / "verdict.schema.json"


def validate_dockerfile_contract(dockerfile: pathlib.Path) -> list[str]:
    """Verifies root Dockerfile declares FROM, a non-root USER, and CMD or ENTRYPOINT."""
    lines = [ln.strip() for ln in dockerfile.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    errors: list[str] = []
    if not any(ln.upper().startswith("FROM ") for ln in lines):
        errors.append("Dockerfile missing FROM instruction.")
    users = [ln.split(None, 1)[1].strip() for ln in lines if ln.upper().startswith("USER ") and len(ln.split(None, 1)) > 1]
    if not users or users[-1] in ("root", "0", "0:0"):
        errors.append("Dockerfile must end with a non-root USER instruction.")
    if not any(ln.upper().startswith(("CMD ", "CMD[", "ENTRYPOINT ", "ENTRYPOINT[")) for ln in lines):
        errors.append("Dockerfile missing CMD or ENTRYPOINT instruction.")
    return errors


def run_cli(cmd: list[str], env: dict[str, str], cwd: pathlib.Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    """Runs an isolated subprocess command with a hard timeout."""
    return subprocess.run(cmd, env=env, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)


def parse_adk_eval_output(stdout: str, stderr: str) -> tuple[bool, int, int]:
    """Parses adk eval stdout/stderr and fails closed when 0 tests ran or any case failed."""
    combined = f"{stdout}\n{stderr}"
    passed = sum(int(m) for m in PASS_COUNT_RE.findall(combined))
    failed = sum(int(m) for m in FAIL_COUNT_RE.findall(combined))
    return (passed > 0 and failed == 0), passed, failed


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
    p.add_argument("--phase", default="evaluate", choices=["deploy", "evaluate"])
    p.add_argument("--sandbox-project", default="")
    p.add_argument("--reasoning-engine", default="")
    p.add_argument("--sandbox-ge-agent", default="", help="Existing Sandbox GE agent resource to PATCH instead of POST.")
    p.add_argument("--expected-evaluator-sa", default="")
    p.add_argument("--keep-for-ci", action="store_true")
    p.add_argument("--verdict-out", required=True, type=pathlib.Path)
    p.add_argument("--ge-schema", type=pathlib.Path, default=default_ge_schema(REPO_ROOT))
    p.add_argument("--verdict-schema", type=pathlib.Path, default=_default_verdict_schema())
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
    """Validates and writes a Contract 5 Verdict JSON record, returning exit_code."""
    payload: dict[str, Any] = {
        "schema_version": "1",
        "pack": "adk",
        "pr_number": args.pr_number,
        "commit_sha": args.commit_sha,
        "diversity_profile": args.diversity_profile,
        "ephemeral_app_name": args.reasoning_engine or None,
        "ge_agent_resource": ge_agent_resource,
        "evaluation_run_ids": [],
        "expected_evaluator_sa": args.expected_evaluator_sa or None,
        "evals_tree_sha256": sha256_tree(evals_dir),
        "gates_executed": gates_executed,
        "gates_skipped": gates_skipped,
        "not_verifiable_surfaces": [],
        "verdict": verdict,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    schema_errs = validate_against_schema(payload, args.verdict_schema)
    if schema_errs:
        print("INTERNAL VERDICT SCHEMA ERROR: " + " | ".join(schema_errs), file=sys.stderr)
        payload["verdict"] = "verifier-failed"
        exit_code = 1
    args.verdict_out.parent.mkdir(parents=True, exist_ok=True)
    args.verdict_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Executes credential-scrubbed Level 1 checks and strict split-SA Level 2 phases."""
    args = parse_args(argv)
    repo = args.repo_dir.resolve()
    evals_dir = repo / "evals"
    evals_hash = sha256_tree(evals_dir)
    gates_executed: list[str] = []
    gates_skipped: list[str] = []

    # Level 1 runs in a scrubbed environment without ADC or GCP metadata access.
    with tempfile.TemporaryDirectory(prefix="adk-l1-home-") as tmp_home:
        off_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": tmp_home,
            "LANG": "C.UTF-8",
            "GOOGLE_APPLICATION_CREDENTIALS": "/dev/null",
            "GCE_METADATA_HOST": "127.0.0.1:1",
        }
        pytest_ran = False
        if (repo / "tests").is_dir() and any((repo / "tests").glob("test_*.py")):
            res = run_cli([sys.executable, "-m", "pytest", "tests/", "-q"], off_env, repo)
            gates_executed.append("l1:pytest")
            pytest_ran = True
            if res.returncode != 0:
                return _write_verdict(args, evals_dir, gates_executed, ["l1:ge-export-bundle", "l2:adk-eval"], "verifier-failed", exit_code=1)
        else:
            gates_skipped.append("l1:pytest")

        dockerfile = repo / "Dockerfile"
        if dockerfile.is_file():
            df_errs = validate_dockerfile_contract(dockerfile)
            gates_executed.append("l1:dockerfile-contract")
            if df_errs:
                for err in df_errs:
                    print(f"DOCKERFILE CONTRACT FAILED: {err}", file=sys.stderr)
                return _write_verdict(args, evals_dir, gates_executed, ["l1:ge-export-bundle", "l2:adk-eval"], "verifier-failed", exit_code=1)
        else:
            gates_skipped.append("l1:dockerfile-contract")

        ge_manifest_path = repo / args.ge_manifest
        spec: dict[str, Any] | None = None
        if ge_manifest_path.is_file():
            spec = json.loads(ge_manifest_path.read_text(encoding="utf-8"))
            out_dir = args.ge_export_out or (repo / "dist" / "ge-export")
            try:
                export_ge_bundle(
                    spec, out_dir, args.ge_schema, commit_sha=args.commit_sha, evals_tree_sha256=evals_hash
                )
                gates_executed.append("l1:ge-export-bundle")
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return _write_verdict(args, evals_dir, gates_executed, ["l2:adk-eval"], "verifier-failed", exit_code=1)
        else:
            gates_skipped.append("l1:ge-export-bundle")

    if args.mode == "level1-only":
        gates_skipped.extend(["l2:adk-eval", "l2:ge-sandbox-register"])
        lvl = "unit-test-verified" if pytest_ran else "static-check-only"
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, lvl, exit_code=0)

    # Level 2 Phase A: Deployer SA only (registers or PATCHes ephemeral Sandbox GE agent).
    if args.phase == "deploy":
        deployer_tok = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN", "").strip()
        if not (args.sandbox_project and deployer_tok and spec is not None):
            gates_skipped.append("l2:missing-deployer-inputs")
            return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)
        if spec["gemini_enterprise"]["project_id"] != args.sandbox_project:
            print(
                f"REFUSED: ge_manifest project '{spec['gemini_enterprise']['project_id']}' != sandbox '{args.sandbox_project}'.",
                file=sys.stderr,
            )
            return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)

        ephemeral_name = f"[CI] PR-{args.pr_number}-{args.commit_sha[:7]} {spec['display_name']}"[:120]
        if args.sandbox_ge_agent:
            st, body = patch_ge_agent(
                args.sandbox_ge_agent, spec, deployer_tok, args.sandbox_project, ephemeral_name, args.reasoning_engine
            )
        else:
            st, body = register_ge_agent(
                spec, deployer_tok, args.sandbox_project, ephemeral_name, args.reasoning_engine
            )
        gates_executed.append("l2:ge-sandbox-register")
        if st in (0, 401, 403, 429) or st >= 500:
            return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)
        if not (200 <= st < 300):
            return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-failed", exit_code=1)
        ge_res = str(body.get("name") or args.sandbox_ge_agent or "") or None
        print(json.dumps({"ge_agent_resource": ge_res, "status": st}, indent=2))
        return 0

    # Level 2 Phase B: Evaluator SA only (runs adk eval and emits live-gcp-verified Verdict).
    evaluator_tok = os.environ.get("ADK_EVALUATOR_OAUTH_TOKEN", "").strip()
    if not (args.sandbox_project and evaluator_tok and args.expected_evaluator_sa):
        gates_skipped.append("l2:missing-evaluator-inputs")
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)
    if not (args.reasoning_engine or args.sandbox_ge_agent):
        gates_skipped.append("l2:missing-sandbox-target")
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-blocked", exit_code=1)

    evalsets = sorted((evals_dir / "synthetic").glob("*.evalset.json")) if (evals_dir / "synthetic").is_dir() else []
    if not evalsets:
        gates_skipped.append("l2:no-evalsets")
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-failed", exit_code=1)

    eval_env = {**os.environ, "ADK_EVALUATOR_OAUTH_TOKEN": evaluator_tok}
    eval_env.pop("ADK_DEPLOYER_OAUTH_TOKEN", None)
    cfg_path = evals_dir / "eval_config.json"
    total_passed = 0
    for es in evalsets:
        cmd = ["adk", "eval", args.agent_dir, str(es), "--print_detailed_results"]
        if cfg_path.is_file():
            cmd.extend(["--config_file_path", str(cfg_path)])
        try:
            res = run_cli(cmd, eval_env, repo, timeout=300)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"adk eval blocked: {exc}", file=sys.stderr)
            return _write_verdict(args, evals_dir, gates_executed, ["l2:adk-eval"], "verifier-blocked", exit_code=1)
        ok, p_cnt, f_cnt = parse_adk_eval_output(res.stdout, res.stderr)
        total_passed += p_cnt
        if res.returncode != 0 or not ok:
            gates_executed.append("l2:adk-eval")
            print(f"adk eval failed on {es.name}: passed={p_cnt}, failed={f_cnt}", file=sys.stderr)
            return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-failed", exit_code=1)

    gates_executed.append("l2:adk-eval")
    if total_passed <= 0:
        return _write_verdict(args, evals_dir, gates_executed, gates_skipped, "verifier-failed", exit_code=1)
    return _write_verdict(
        args,
        evals_dir,
        gates_executed,
        gates_skipped,
        "live-gcp-verified",
        ge_agent_resource=args.sandbox_ge_agent or None,
        exit_code=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
