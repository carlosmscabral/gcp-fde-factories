#!/usr/bin/env python3
"""Split-SA Level 1 + Level 2 verification runner and Verdict emitter for packs/gecx.

Replaces single-SA `cxas ci-test` with an explicit split-SA sequence validated in Gate 0 Spike:
1. Level 1 (offline): cxas lint + Foundry sync-callbacks.py --from-local + cxas test-callbacks.
2. Level 2 (Sandbox): deployer pushes [CI] app + evals, evaluator runs test-tools and
   `cxas run --eval-type all --wait` (avoiding cxas 1.11.0 WK-001 CLI bug), then reads
   GET /v1beta/<app>/evaluationRuns directly to enforce totalCount > 0 and failedCount == 0.
3. Teardown rule: deletes the ephemeral [CI] app on failure or iteration mode; keeps passing
   PR apps alive (capped by the 4-hour hourly Janitor) so GitHub Actions CI reads evaluationRuns
   without HTTP 404 before deleting the app in `if: always()`.
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
import urllib.error
import urllib.request
from typing import Any


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


def ces_rest_get(url: str, token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated GET against the CES v1beta REST API."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": quota_project,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")}


def evaluate_rest_runs(
    runs: list[dict[str, Any]], expected_evaluator_sa: str | None = None
) -> tuple[bool, list[str], list[str]]:
    """Enforces fail-closed pass criteria on CES evaluationRuns payloads.

    Returns (passed, run_names, failure_reasons). Fails closed when zero runs or zero cases exist.
    """
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
        count = int(progress.get("totalCount", 0) or 0)
        failed = int(progress.get("failedCount", 0) or 0)
        total_cases += count
        total_failed += failed
        state = str(run.get("state") or "")
        if state and state.upper() not in ("SUCCEEDED", "COMPLETED", "STATE_UNSPECIFIED"):
            reasons.append(f"Run {name} ended in non-passing state '{state}'.")
        if expected_evaluator_sa:
            initiated_by = str(run.get("initiatedBy") or "")
            if initiated_by and expected_evaluator_sa not in initiated_by:
                reasons.append(
                    f"Run {name} initiatedBy '{initiated_by}' does not match '{expected_evaluator_sa}'."
                )

    if total_cases <= 0:
        reasons.append("CES evaluationRuns executed 0 total test cases (fail-closed).")
    if total_failed > 0:
        reasons.append(f"CES evaluationRuns recorded {total_failed} failed case(s).")

    return len(reasons) == 0, run_names, reasons


def run_cli(cmd: list[str], env: dict[str, str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Runs a subprocess command with explicit environment and captures output."""
    return subprocess.run(cmd, env=env, cwd=str(cwd), text=True, capture_output=True)


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
    p.add_argument("--diversity-profile", default="cross-vendor", choices=["cross-vendor", "cross-model", "single-family"])
    p.add_argument("--sandbox-project", default="")
    p.add_argument("--location", default="us")
    p.add_argument("--agent-name", default="gecx-eval-tester")
    p.add_argument("--mode", default="level1-only", choices=["level1-only", "sandbox-live"])
    p.add_argument("--keep-app-for-ci", action="store_true", help="Keep passing [CI] app alive for GitHub Actions verification.")
    p.add_argument("--expected-evaluator-sa", default="")
    p.add_argument("--verdict-out", required=True, type=pathlib.Path)
    p.add_argument("--cxas-bin", default="cxas")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Runs configured verification levels and writes a schema-valid Verdict JSON."""
    args = parse_args(argv)
    repo = args.repo_dir.resolve()
    app_dir = (repo / args.app_rel_dir).resolve()
    evals_dir = repo / "evals"
    foundry_dir = pathlib.Path(os.environ.get("GECX_FOUNDRY_DIR", "/opt/gecx-foundry"))

    gates_executed: list[str] = []
    gates_skipped: list[str] = []
    off_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}

    # Level 1: Strictly offline checks (zero GCP credentials).
    lint_res = run_cli([args.cxas_bin, "--no-input", "lint", "--app-dir", str(app_dir)], off_env, repo)
    gates_executed.append("l1:cxas-lint")
    if lint_res.returncode != 0:
        verdict_val = "verifier-failed"
        return _write_and_exit(args, evals_dir, gates_executed, ["l1:callbacks", "l2:sandbox"], None, [], verdict_val, 1)

    sync_script = foundry_dir / "scripts" / "sync-callbacks.py"
    cb_dir = evals_dir / "callback_tests"
    if sync_script.exists() and cb_dir.exists():
        run_cli([sys.executable, str(sync_script), "--from-local", str(app_dir)], off_env, repo)
        cb_res = run_cli([args.cxas_bin, "--no-input", "test-callbacks", "--app-dir", str(cb_dir)], off_env, repo)
        gates_executed.append("l1:cxas-test-callbacks")
        if cb_res.returncode != 0:
            return _write_and_exit(args, evals_dir, gates_executed, ["l2:sandbox"], None, [], "verifier-failed", 1)
    else:
        gates_skipped.append("l1:cxas-test-callbacks")

    if args.mode == "level1-only":
        gates_skipped.extend(["l2:deployer-push", "l2:evaluator-test-tools", "l2:evaluator-run"])
        return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, None, [], "unit-test-verified", 0)

    # Level 2: Live split-SA Sandbox lifecycle (requires pre-minted short-lived SA tokens in env).
    deployer_tok = os.environ.get("GECX_DEPLOYER_OAUTH_TOKEN", "")
    evaluator_tok = os.environ.get("GECX_EVALUATOR_OAUTH_TOKEN", "")
    janitor_tok = os.environ.get("GECX_JANITOR_OAUTH_TOKEN", deployer_tok)
    if not (args.sandbox_project and deployer_tok and evaluator_tok):
        gates_skipped.append("l2:missing-sandbox-tokens")
        return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, None, [], "verifier-blocked", 1)

    sbx_env = dict(off_env)
    sbx_env["GOOGLE_CLOUD_QUOTA_PROJECT"] = args.sandbox_project
    sbx_env["GOOGLE_CLOUD_PROJECT"] = args.sandbox_project
    display_name = f"[CI] PR-{args.pr_number}-{args.commit_sha[:7]}-{args.agent_name}"
    app_resource: str | None = None
    passed = False
    run_ids: list[str] = []

    try:
        push_res = run_cli(
            [args.cxas_bin, "--no-input", "--oauth-token", deployer_tok, "push",
             "--app-dir", str(app_dir), "--project-id", args.sandbox_project,
             "--location", args.location, "--display-name", display_name],
            sbx_env, repo,
        )
        gates_executed.append("l2:deployer-push")
        if push_res.returncode != 0:
            return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, None, [], "verifier-failed", 1)

        _, apps_body = ces_rest_get(
            f"https://ces.googleapis.com/v1beta/projects/{args.sandbox_project}/locations/{args.location}/apps",
            evaluator_tok, args.sandbox_project,
        )
        matches = [a for a in apps_body.get("apps", []) if str(a.get("displayName", "")).startswith(display_name)]
        if not matches:
            return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, None, [], "verifier-failed", 1)
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
            run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", deployer_tok, "push-eval",
                 "--app-name", app_resource, "--file", str(eval_file)],
                sbx_env, repo,
            )
        gates_executed.append("l2:deployer-push-eval")

        for tool_file in sorted((evals_dir / "tool_tests").glob("*.yaml")) if (evals_dir / "tool_tests").exists() else []:
            tt_res = run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", evaluator_tok, "test-tools",
                 "--app-name", app_resource, "--test-file", str(tool_file)],
                sbx_env, repo,
            )
            if tt_res.returncode != 0:
                return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, app_resource, [], "verifier-failed", 1)
        gates_executed.append("l2:evaluator-test-tools")

        # Workaround WK-001: omit --min-pass-rate with --eval-type all; gate via REST evaluationRuns below.
        run_cli(
            [args.cxas_bin, "--no-input", "--oauth-token", evaluator_tok, "run",
             "--app-name", app_resource, "--eval-type", "all", "--wait"],
            sbx_env, repo,
        )
        gates_executed.append("l2:evaluator-run")

        _, runs_body = ces_rest_get(f"https://ces.googleapis.com/v1beta/{app_resource}/evaluationRuns", evaluator_tok, args.sandbox_project)
        passed, run_ids, reasons = evaluate_rest_runs(
            runs_body.get("evaluationRuns", []), args.expected_evaluator_sa or None
        )
        if not passed:
            print("REST evaluationRuns gate failed:", "; ".join(reasons), file=sys.stderr)
            return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, app_resource, run_ids, "verifier-failed", 1)

        return _write_and_exit(args, evals_dir, gates_executed, gates_skipped, app_resource, run_ids, "live-gcp-verified", 0)
    finally:
        # Delete failed or intermediate apps immediately; keep passing PR apps only when --keep-app-for-ci is set.
        if app_resource and janitor_tok and not (passed and args.keep_app_for_ci):
            run_cli(
                [args.cxas_bin, "--no-input", "--oauth-token", janitor_tok, "delete",
                 "--app-name", app_resource, "--force"],
                sbx_env, repo,
            )


def _write_and_exit(
    args: argparse.Namespace,
    evals_dir: pathlib.Path,
    gates_executed: list[str],
    gates_skipped: list[str],
    app_resource: str | None,
    run_ids: list[str],
    verdict: str,
    exit_code: int,
) -> int:
    """Writes the Verdict JSON matching schemas/verdict.schema.json and returns exit_code."""
    payload = {
        "schema_version": "1",
        "pr_number": args.pr_number,
        "commit_sha": args.commit_sha,
        "diversity_profile": args.diversity_profile,
        "ephemeral_app_name": app_resource,
        "evaluation_run_ids": run_ids,
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


if __name__ == "__main__":
    raise SystemExit(main())
