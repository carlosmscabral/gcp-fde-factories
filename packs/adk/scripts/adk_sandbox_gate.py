#!/usr/bin/env python3
"""Split-SA Level 1 + Level 2 verification runner and Contract 5 Verdict emitter for packs/adk.

Enforces real split-SA separation:
- Level 1 (offline, scrubbed HOME/ADC): pytest, final-stage root Dockerfile contract check,
  and GE export bundle check. Emits 'static-check-only' when no tests executed and
  'unit-test-verified' only when pytest passes.
- Level 2 deploy phase (Deployer SA only): refuses non-sandbox targets, validates
  --reasoning-engine project binding, registers or PATCHes ephemeral GE agent, and writes
  an optional state handoff file for the evaluate phase.
- Level 2 evaluate phase (Evaluator SA only): runs credential-scrubbed `adk eval` with strict
  result parsing (fails closed on 0 cases or any failure) and self-validates the Verdict JSON.
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

import yaml

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
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
    )
except ModuleNotFoundError:
    from lib.ge_payload import (
        default_ge_schema,
        export_ge_bundle,
        patch_ge_agent,
        register_ge_agent,
    )

PASS_COUNT_RE = re.compile(r"Tests passed:\s*(\d+)", re.I)
FAIL_COUNT_RE = re.compile(r"Tests failed:\s*(\d+)", re.I)
REASONING_ENGINE_RE = re.compile(
    r"^projects/([a-z0-9-]+)/locations/[a-z0-9-]+/reasoningEngines/[A-Za-z0-9_-]+$"
)
ALL_GATES = (
    "l1:pytest",
    "l1:dockerfile-contract",
    "l1:ge-export-bundle",
    "l2:ge-sandbox-register",
    "l2:adk-eval",
)


def _default_verdict_schema() -> pathlib.Path:
    """Locates schemas/verdict.schema.json inside repo or container /opt/gcp-fde."""
    for cand in (
        REPO_ROOT / "schemas" / "verdict.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/verdict.schema.json"),
    ):
        if cand.is_file():
            return cand
    return REPO_ROOT / "schemas" / "verdict.schema.json"


def _default_diversity_profile(repo: pathlib.Path) -> str:
    """Reads diversity_profile from .factory/hub-project.yaml or falls back to cross-model."""
    cfg_path = repo / ".factory" / "hub-project.yaml"
    if cfg_path.is_file():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                val = str(data.get("diversity_profile") or "")
                if val in ("cross-vendor", "cross-model", "single-family"):
                    return val
        except (OSError, yaml.YAMLError):
            pass
    return "cross-model"


def validate_dockerfile_contract(dockerfile: pathlib.Path) -> list[str]:
    """Verifies final FROM stage declares an explicit non-root USER and CMD or ENTRYPOINT."""
    raw_lines = [
        ln.strip()
        for ln in dockerfile.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    stages: list[list[str]] = []
    for ln in raw_lines:
        if ln.upper().startswith("FROM "):
            stages.append([ln])
        elif stages:
            stages[-1].append(ln)
    if not stages:
        return ["Dockerfile missing FROM instruction."]

    final_stage = stages[-1]
    errors: list[str] = []
    users = [
        ln.split(None, 1)[1].strip()
        for ln in final_stage
        if ln.upper().startswith("USER ") and len(ln.split(None, 1)) > 1
    ]
    if not users:
        errors.append("Final Dockerfile stage must declare a non-root USER instruction.")
    else:
        final_user = users[-1]
        user_part = final_user.split(":", 1)[0].strip().lower()
        if "$" in final_user:
            errors.append(f"Final Dockerfile USER '{final_user}' must be literal, not a variable.")
        elif user_part in ("root", "0", ""):
            errors.append(f"Final Dockerfile stage must end with a non-root USER, got '{final_user}'.")

    has_entrypoint = any(
        ln.upper().startswith(("CMD ", "CMD[", "ENTRYPOINT ", "ENTRYPOINT["))
        for ln in final_stage
    )
    if not has_entrypoint:
        errors.append("Final Dockerfile stage missing CMD or ENTRYPOINT instruction.")
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
    p.add_argument("--diversity-profile", default="", choices=["", "cross-vendor", "cross-model", "single-family"])
    p.add_argument("--mode", default="level1-only", choices=["level1-only", "sandbox-live"])
    p.add_argument("--phase", default="evaluate", choices=["deploy", "evaluate"])
    p.add_argument("--sandbox-project", default="")
    p.add_argument("--sandbox-project-number", default=os.environ.get("SANDBOX_PROJECT_NUMBER", ""))
    p.add_argument("--reasoning-engine", default="")
    p.add_argument("--sandbox-ge-agent", default="", help="Existing Sandbox GE agent resource to PATCH instead of POST.")
    p.add_argument("--ge-agent-state-file", type=pathlib.Path, default=None, help="JSON handoff file from deploy to evaluate phase.")
    p.add_argument("--expected-evaluator-sa", default="")
    p.add_argument("--verdict-out", required=True, type=pathlib.Path)
    p.add_argument("--ge-schema", type=pathlib.Path, default=default_ge_schema(REPO_ROOT))
    p.add_argument("--verdict-schema", type=pathlib.Path, default=_default_verdict_schema())
    return p.parse_args(argv)


def _remaining_gates(executed: list[str], extra_skipped: list[str] | None = None) -> list[str]:
    """Computes deterministic gates_skipped list from ALL_GATES plus any explicit skip markers."""
    seen = set(executed)
    out = [g for g in ALL_GATES if g not in seen]
    for item in extra_skipped or []:
        if item not in out and item not in seen:
            out.append(item)
    return out


def _write_verdict(
    args: argparse.Namespace,
    diversity_profile: str,
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
        "diversity_profile": diversity_profile,
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


def _validate_reasoning_engine_project(
    reasoning_engine: str,
    sandbox_project: str,
    sandbox_project_number: str = "",
) -> str | None:
    """Verifies --reasoning-engine belongs to sandbox_project ID or explicit numeric sandbox_project_number."""
    if not reasoning_engine:
        return None
    m = REASONING_ENGINE_RE.match(reasoning_engine)
    if not m:
        return f"Invalid --reasoning-engine resource format: '{reasoning_engine}'."
    allowed = {p for p in (sandbox_project.strip(), sandbox_project_number.strip()) if p}
    if m.group(1) not in allowed:
        return (
            f"Refusing cross-project --reasoning-engine '{m.group(1)}' != sandbox '{sandbox_project}'"
            + (f" or number '{sandbox_project_number}'." if sandbox_project_number else " (pass --sandbox-project-number for numeric GCP paths).")
        )
    return None


def main(argv: list[str] | None = None) -> int:
    """Executes credential-scrubbed Level 1 checks and strict split-SA Level 2 phases."""
    args = parse_args(argv)
    repo = args.repo_dir.resolve()
    diversity_profile = args.diversity_profile or _default_diversity_profile(repo)
    evals_dir = repo / "evals"
    evals_hash = sha256_tree(evals_dir)
    gates_executed: list[str] = []

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
                return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)

        dockerfile = repo / "Dockerfile"
        if dockerfile.is_file():
            df_errs = validate_dockerfile_contract(dockerfile)
            gates_executed.append("l1:dockerfile-contract")
            if df_errs:
                for err in df_errs:
                    print(f"DOCKERFILE CONTRACT FAILED: {err}", file=sys.stderr)
                return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)

        ge_manifest_path = repo / args.ge_manifest
        spec: dict[str, Any] | None = None
        if ge_manifest_path.is_file():
            try:
                spec = json.loads(ge_manifest_path.read_text(encoding="utf-8"))
                if not isinstance(spec, dict):
                    raise ValueError("ge_manifest.json must contain a JSON object.")
                out_dir = args.ge_export_out or (repo / "dist" / "ge-export")
                export_ge_bundle(
                    spec, out_dir, args.ge_schema, commit_sha=args.commit_sha, evals_tree_sha256=evals_hash
                )
                gates_executed.append("l1:ge-export-bundle")
            except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
                print(f"GE EXPORT FAILED: {exc}", file=sys.stderr)
                return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)

    if args.mode == "level1-only":
        lvl = "unit-test-verified" if pytest_ran else "static-check-only"
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), lvl, exit_code=0)

    # Level 2 Phase A: Deployer SA only (registers or PATCHes ephemeral Sandbox GE agent).
    if args.phase == "deploy":
        deployer_tok = os.environ.get("ADK_DEPLOYER_OAUTH_TOKEN", "").strip()
        if not (args.sandbox_project and deployer_tok and spec is not None):
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed, ["l2:missing-deployer-inputs"]), "verifier-blocked", exit_code=1)
        if spec["gemini_enterprise"]["project_id"] != args.sandbox_project:
            print(
                f"REFUSED: ge_manifest project '{spec['gemini_enterprise']['project_id']}' != sandbox '{args.sandbox_project}'.",
                file=sys.stderr,
            )
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)
        re_err = _validate_reasoning_engine_project(args.reasoning_engine, args.sandbox_project, args.sandbox_project_number)
        if re_err:
            print(f"REFUSED: {re_err}", file=sys.stderr)
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)

        ephemeral_name = f"[CI] PR-{args.pr_number}-{args.commit_sha[:7]} {spec['display_name']}"[:120]
        try:
            if args.sandbox_ge_agent:
                st, body = patch_ge_agent(
                    args.sandbox_ge_agent,
                    spec,
                    deployer_tok,
                    args.sandbox_project,
                    ephemeral_name,
                    args.reasoning_engine,
                    quota_project_number=args.sandbox_project_number,
                )
            else:
                st, body = register_ge_agent(
                    spec, deployer_tok, args.sandbox_project, ephemeral_name, args.reasoning_engine
                )
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)
        gates_executed.append("l2:ge-sandbox-register")
        if st in (0, 401, 403, 429) or st >= 500:
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)
        if not (200 <= st < 300):
            return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)
        ge_res = str(body.get("name") or args.sandbox_ge_agent or "") or None
        handoff = {"ge_agent_resource": ge_res, "reused": bool(args.sandbox_ge_agent), "status": st}
        if args.ge_agent_state_file:
            args.ge_agent_state_file.parent.mkdir(parents=True, exist_ok=True)
            args.ge_agent_state_file.write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(handoff, indent=2))
        return 0

    # Level 2 Phase B: Evaluator SA only (runs scrubbed adk eval and emits live-gcp-verified Verdict).
    evaluator_tok = os.environ.get("ADK_EVALUATOR_OAUTH_TOKEN", "").strip()
    resolved_ge_agent = args.sandbox_ge_agent
    if not resolved_ge_agent and args.ge_agent_state_file and args.ge_agent_state_file.is_file():
        try:
            state = json.loads(args.ge_agent_state_file.read_text(encoding="utf-8"))
            if isinstance(state, dict) and state.get("ge_agent_resource"):
                resolved_ge_agent = str(state["ge_agent_resource"])
        except (OSError, json.JSONDecodeError):
            pass

    if not (args.sandbox_project and evaluator_tok and args.expected_evaluator_sa):
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed, ["l2:missing-evaluator-inputs"]), "verifier-blocked", exit_code=1)
    re_err = _validate_reasoning_engine_project(args.reasoning_engine, args.sandbox_project, args.sandbox_project_number)
    if re_err:
        print(f"REFUSED: {re_err}", file=sys.stderr)
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)
    if not (args.reasoning_engine or resolved_ge_agent):
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed, ["l2:missing-sandbox-target"]), "verifier-blocked", exit_code=1)

    evalsets = sorted((evals_dir / "synthetic").glob("*.evalset.json")) if (evals_dir / "synthetic").is_dir() else []
    if not evalsets:
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed, ["l2:no-evalsets"]), "verifier-failed", exit_code=1)

    # Scrub ambient Deployer credentials and isolate Evaluator token + Sandbox project explicitly.
    # Preserve container metadata and TLS CA env vars so google-auth works inside Scion Docker/GKE pods.
    with tempfile.TemporaryDirectory(prefix="adk-l2-eval-") as eval_home:
        eval_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": eval_home,
            "LANG": "C.UTF-8",
            "GOOGLE_CLOUD_PROJECT": args.sandbox_project,
            "GOOGLE_CLOUD_LOCATION": os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
            "GOOGLE_GENAI_USE_VERTEXAI": "1",
            "CLOUDSDK_AUTH_ACCESS_TOKEN": evaluator_tok,
            "ADK_EVALUATOR_OAUTH_TOKEN": evaluator_tok,
        }
        for passthrough in ("GCE_METADATA_HOST", "GCE_METADATA_ROOT", "SSL_CERT_FILE", "SSL_CERT_DIR"):
            if os.environ.get(passthrough):
                eval_env[passthrough] = os.environ[passthrough]
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
                return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-blocked", exit_code=1)
            ok, p_cnt, f_cnt = parse_adk_eval_output(res.stdout, res.stderr)
            total_passed += p_cnt
            if res.returncode != 0 or not ok:
                gates_executed.append("l2:adk-eval")
                print(f"adk eval failed on {es.name}: passed={p_cnt}, failed={f_cnt}", file=sys.stderr)
                return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)

    gates_executed.append("l2:adk-eval")
    if total_passed <= 0:
        return _write_verdict(args, diversity_profile, evals_dir, gates_executed, _remaining_gates(gates_executed), "verifier-failed", exit_code=1)
    return _write_verdict(
        args,
        diversity_profile,
        evals_dir,
        gates_executed,
        _remaining_gates(gates_executed),
        "live-gcp-verified",
        ge_agent_resource=resolved_ge_agent or None,
        exit_code=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
