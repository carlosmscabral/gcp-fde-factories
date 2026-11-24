#!/usr/bin/env python3
"""Split-SA Level 1 + Level 2 verification runner and schema-validated Verdict emitter for packs/gecx.

Executes credential-scrubbed Level 1 checks (cxas lint + optional callback tests), then
explicit split-SA Level 2 Sandbox deploy/eval with paginated CES evaluationRuns verification,
and self-validates the Verdict JSON against schemas/verdict.schema.json before writing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import yaml

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
for cand in (str(REPO_ROOT), "/opt/gcp-fde"):
    if pathlib.Path(cand).exists() and cand not in sys.path:
        sys.path.insert(0, cand)

from scripts.lib.io_utils import sha256_tree
from scripts.lib.schema_validator import validate_against_schema

ALL_GATES = (
    "l1:cxas-lint",
    "l1:cxas-test-callbacks",
    "l2:deployer-push",
    "l2:deployer-push-eval",
    "l2:evaluator-test-tools",
    "l2:evaluator-run",
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


def _read_diversity_default(repo: pathlib.Path) -> str:
    """Reads diversity_profile from .factory/hub-project.yaml, defaulting to cross-model."""
    cfg_path = repo / ".factory" / "hub-project.yaml"
    if cfg_path.is_file():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("diversity_profile") in ("cross-vendor", "cross-model", "single-family"):
                return str(data["diversity_profile"])
        except (OSError, yaml.YAMLError):
            pass
    return "cross-model"


def ces_rest_get(url: str, token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated GET against the CES v1beta REST API with safe error handling."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": quota_project},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
        return code, {"error": str(exc)}


def _ces_list_paginated(base_url: str, key: str, token: str, quota_project: str) -> tuple[bool, list[dict[str, Any]]]:
    """Fetches all pages for a CES v1beta list endpoint."""
    items: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(20):
        url = f"{base_url}?pageToken={urllib.parse.quote(page_token)}" if page_token else base_url
        st, body = ces_rest_get(url, token, quota_project)
        if st != 200:
            return False, []
        items.extend(body.get(key, []) or [])
        page_token = str(body.get("nextPageToken") or "")
        if not page_token:
            return True, items
    return True, items


def evaluate_rest_runs(
    runs: list[dict[str, Any]], expected_evaluator_sa: str | None = None
) -> tuple[bool, list[str], list[str]]:
    """Enforces fail-closed pass criteria on CES evaluationRuns payloads."""
    reasons: list[str] = []
    run_names: list[str] = []
    if not runs:
        return False, [], ["CES evaluationRuns returned 0 runs (fail-closed)."]

    total_cases = 0
    total_failed = 0
    for run in runs:
        name = str(run.get("name", ""))
        if name:
            run_names.append(name)
        progress = run.get("progress") or {}
        total_cases += int(progress.get("totalCount", 0) or 0)
        total_failed += int(progress.get("failedCount", 0) or 0)
        state = str(run.get("state") or "")
        if state and state.upper() not in ("SUCCEEDED", "COMPLETED", "STATE_UNSPECIFIED"):
            reasons.append(f"Run {name} ended in non-passing state '{state}'.")
        if expected_evaluator_sa:
            initiated_by = str(run.get("initiatedBy") or "")
            if initiated_by and expected_evaluator_sa not in initiated_by:
                reasons.append(f"Run {name} initiatedBy '{initiated_by}' does not match '{expected_evaluator_sa}'.")

    if total_cases <= 0:
        reasons.append("CES evaluationRuns executed 0 total test cases (fail-closed).")
    if total_failed > 0:
        reasons.append(f"CES evaluationRuns recorded {total_failed} failed case(s).")
    return len(reasons) == 0, run_names, reasons


def run_cli(cmd: list[str], env: dict[str, str], cwd: pathlib.Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Runs a subprocess command with explicit environment and hard timeout."""
    return subprocess.run(cmd, env=env, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)


def append_ledger(ledger_path: pathlib.Path, entry: dict[str, Any]) -> None:
    """Appends one JSONL audit entry to the Sandbox ledger."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses CLI flags for the split-SA GECX verification gate."""
    p = argparse.ArgumentParser(description="Run GECX split-SA Level 1 + Level 2 verification.")
    p.add_argument("--repo-dir", required=True, type=pathlib.Path)
    p.add_argument("--app-rel-dir", required=True, help="Relative path to cxas_app/<AppName>.")
    p.add_argument("--pr-number", required=True, type=int)
    p.add_argument("--commit-sha", required=True)
    p.add_argument("--diversity-profile", default="", choices=["", "cross-vendor", "cross-model", "single-family"])
    p.add_argument("--sandbox-project", default="")
    p.add_argument("--location", default="us")
    p.add_argument("--agent-name", default="gecx-eval-tester")
    p.add_argument("--mode", default="level1-only", choices=["level1-only", "sandbox-live"])
    p.add_argument("--keep-app-for-ci", action="store_true")
    p.add_argument("--expected-evaluator-sa", default="")
    p.add_argument("--verdict-out", required=True, type=pathlib.Path)
    p.add_argument("--verdict-schema", type=pathlib.Path, default=_default_verdict_schema())
    p.add_argument("--cxas-bin", default="cxas")
    return p.parse_args(argv)


def _write_and_exit(
    args: argparse.Namespace,
    diversity: str,
    evals_dir: pathlib.Path,
    gates_executed: list[str],
    app_resource: str | None,
    run_ids: list[str],
    verdict: str,
    exit_code: int,
) -> int:
    """Validates and writes a Contract 5 Verdict JSON matching schemas/verdict.schema.json."""
    skipped = [g for g in ALL_GATES if g not in gates_executed]
    payload: dict[str, Any] = {
        "schema_version": "1",
        "pack": "gecx",
        "pr_number": args.pr_number,
        "commit_sha": args.commit_sha,
        "diversity_profile": diversity,
        "ephemeral_app_name": app_resource,
        "evaluation_run_ids": run_ids,
        "expected_evaluator_sa": args.expected_evaluator_sa or None,
        "evals_tree_sha256": sha256_tree(evals_dir),
        "gates_executed": gates_executed,
        "gates_skipped": skipped,
        "not_verifiable_surfaces": [],
        "verdict": verdict,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if args.verdict_schema.is_file():
        schema_errs = validate_against_schema(payload, args.verdict_schema)
        if schema_errs:
            print("GECX VERDICT SELF-VALIDATION FAILED:", "; ".join(schema_errs), file=sys.stderr)
            payload["verdict"] = "verifier-failed"
            exit_code = 1
    args.verdict_out.parent.mkdir(parents=True, exist_ok=True)
    args.verdict_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Runs configured verification levels and writes a schema-validated Verdict JSON."""
    args = parse_args(argv)
    repo = args.repo_dir.resolve()
    diversity = args.diversity_profile or _read_diversity_default(repo)
    app_dir = (repo / args.app_rel_dir).resolve()
    evals_dir = repo / "evals"
    foundry_dir = pathlib.Path(os.environ.get("GECX_FOUNDRY_DIR", "/opt/gecx-foundry"))
    gates_executed: list[str] = []

    with tempfile.TemporaryDirectory(prefix="gecx-l1-home-") as tmp_home:
        off_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": tmp_home,
            "LANG": "C.UTF-8",
            "GOOGLE_APPLICATION_CREDENTIALS": "/dev/null",
            "GCE_METADATA_HOST": "127.0.0.1:1",
        }
        lint_res = run_cli([args.cxas_bin, "--no-input", "lint", "--app-dir", str(app_dir)], off_env, repo)
        gates_executed.append("l1:cxas-lint")
        if lint_res.returncode != 0:
            return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-failed", 1)

        callbacks_ran = False
        sync_script = foundry_dir / "scripts" / "sync-callbacks.py"
        cb_dir = evals_dir / "callback_tests"
        if sync_script.exists() and cb_dir.exists():
            sync_res = run_cli([sys.executable, str(sync_script), "--from-local", str(app_dir)], off_env, repo)
            if sync_res.returncode != 0:
                return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-failed", 1)
            cb_res = run_cli([args.cxas_bin, "--no-input", "test-callbacks", "--app-dir", str(cb_dir)], off_env, repo)
            gates_executed.append("l1:cxas-test-callbacks")
            callbacks_ran = True
            if cb_res.returncode != 0:
                return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-failed", 1)

    if args.mode == "level1-only":
        lvl = "unit-test-verified" if callbacks_ran else "static-check-only"
        return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], lvl, 0)

    deployer_tok = os.environ.get("GECX_DEPLOYER_OAUTH_TOKEN", "")
    evaluator_tok = os.environ.get("GECX_EVALUATOR_OAUTH_TOKEN", "")
    janitor_tok = os.environ.get("GECX_JANITOR_OAUTH_TOKEN", deployer_tok)
    if not (args.sandbox_project and deployer_tok and evaluator_tok and args.expected_evaluator_sa):
        return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-blocked", 1)

    sbx_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "GOOGLE_CLOUD_QUOTA_PROJECT": args.sandbox_project,
        "GOOGLE_CLOUD_PROJECT": args.sandbox_project,
    }
    display_name = f"[CI] PR-{args.pr_number}-{args.commit_sha[:7]}-{args.agent_name}"
    app_resource: str | None = None
    passed = False

    try:
        push_res = run_cli(
            [args.cxas_bin, "--no-input", "--oauth-token", deployer_tok, "push",
             "--app-dir", str(app_dir), "--project-id", args.sandbox_project,
             "--location", args.location, "--display-name", display_name],
            sbx_env, repo,
        )
        gates_executed.append("l2:deployer-push")
        if push_res.returncode != 0:
            return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-failed", 1)

        ok_apps, apps = _ces_list_paginated(
            f"https://ces.googleapis.com/v1beta/projects/{args.sandbox_project}/locations/{args.location}/apps",
            "apps", evaluator_tok, args.sandbox_project,
        )
        matches = [a for a in apps if str(a.get("displayName", "")).startswith(display_name)] if ok_apps else []
        if not matches:
            return _write_and_exit(args, diversity, evals_dir, gates_executed, None, [], "verifier-failed", 1)
        app_resource = str(matches[0]["name"])

        ledger = os.environ.get("GECX_SANDBOX_LEDGER")
        if ledger:
            append_ledger(pathlib.Path(ledger), {
                "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "pr_number": args.pr_number,
                "commit_sha": args.commit_sha,
                "display_name": display_name,
                "app_resource": app_resource,
            })

        for eval_file in sorted((evals_dir / "goldens").glob("*.yaml")) if (evals_dir / "goldens").exists() else []:
            pe_res = run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", deployer_tok, "push-eval",
                 "--app-name", app_resource, "--file", str(eval_file)],
                sbx_env, repo,
            )
            if pe_res.returncode != 0:
                return _write_and_exit(args, diversity, evals_dir, gates_executed, app_resource, [], "verifier-failed", 1)
        gates_executed.append("l2:deployer-push-eval")

        for tool_file in sorted((evals_dir / "tool_tests").glob("*.yaml")) if (evals_dir / "tool_tests").exists() else []:
            tt_res = run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", evaluator_tok, "test-tools",
                 "--app-name", app_resource, "--test-file", str(tool_file)],
                sbx_env, repo,
            )
            if tt_res.returncode != 0:
                return _write_and_exit(args, diversity, evals_dir, gates_executed, app_resource, [], "verifier-failed", 1)
        gates_executed.append("l2:evaluator-test-tools")

        # Workaround WK-001: omit --min-pass-rate with --eval-type all and gate via REST evaluationRuns.
        run_cli(
            [args.cxas_bin, "--no-input", "--oauth-token", evaluator_tok, "run",
             "--app-name", app_resource, "--eval-type", "all", "--wait"],
            sbx_env, repo,
        )
        gates_executed.append("l2:evaluator-run")

        ok_runs, runs = _ces_list_paginated(
            f"https://ces.googleapis.com/v1beta/{app_resource}/evaluationRuns",
            "evaluationRuns", evaluator_tok, args.sandbox_project,
        )
        passed, run_ids, reasons = evaluate_rest_runs(runs if ok_runs else [], args.expected_evaluator_sa)
        if not passed:
            print("REST evaluationRuns gate failed:", "; ".join(reasons), file=sys.stderr)
            return _write_and_exit(args, diversity, evals_dir, gates_executed, app_resource, run_ids, "verifier-failed", 1)

        return _write_and_exit(args, diversity, evals_dir, gates_executed, app_resource, run_ids, "live-gcp-verified", 0)
    finally:
        if app_resource and janitor_tok and not (passed and args.keep_app_for_ci):
            run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", janitor_tok, "delete",
                 "--app-name", app_resource, "--force"],
                sbx_env, repo,
            )


if __name__ == "__main__":
    raise SystemExit(main())
