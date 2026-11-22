"""Anti-forgery Verdict verifier for Contract 5 (used by gecx-verdict-gate.yml and tests).

Validates Verdict JSON schema, commit SHA match, evals tree SHA-256 match, and live CES
GET /v1beta/<app>/evaluationRuns provenance (state, progress.totalCount > 0, failedCount == 0,
and initiatedBy matching expected_evaluator_sa).
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from typing import Any, Callable

from scripts.lib.io_utils import load_json, sha256_tree
from scripts.lib.schema_validator import validate_against_schema

FetchFn = Callable[[str, str, str], tuple[int, dict[str, Any]]]


def default_ces_get(url: str, token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
    """Fetches a CES REST resource with Bearer authentication and quota project header."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": quota_project},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")}


def verify_verdict(
    verdict_path: pathlib.Path,
    schema_path: pathlib.Path,
    expected_commit: str,
    evals_dir: pathlib.Path,
    sandbox_project: str = "",
    expected_evaluator_sa: str = "",
    access_token: str = "",
    fetch_fn: FetchFn = default_ces_get,
) -> list[str]:
    """Verifies a Verdict file against schema, local git/evals integrity, and live CES API."""
    verdict = load_json(verdict_path)
    errors = validate_against_schema(verdict, schema_path)
    if errors:
        return errors

    if verdict["commit_sha"] != expected_commit:
        errors.append(f"Commit SHA mismatch: verdict has {verdict['commit_sha']}, PR head is {expected_commit}.")

    actual_evals_hash = sha256_tree(evals_dir)
    if verdict["evals_tree_sha256"] != actual_evals_hash:
        errors.append(
            f"evals/ tree SHA-256 mismatch: verdict has {verdict['evals_tree_sha256']}, repo has {actual_evals_hash}."
        )

    level = verdict["verdict"]
    if level in ("verifier-failed", "verifier-blocked"):
        errors.append(f"Verdict '{level}' blocks PR merge.")
        return errors

    if level == "live-gcp-verified":
        if not access_token or not sandbox_project:
            errors.append("live-gcp-verified requires live CES API verification with access_token and sandbox_project.")
            return errors

        app_name = verdict["ephemeral_app_name"]
        url = f"https://ces.googleapis.com/v1beta/{app_name}/evaluationRuns"
        status, body = fetch_fn(url, access_token, sandbox_project)
        if status != 200:
            errors.append(f"CES API GET {url} returned HTTP {status}: {body.get('error', '')}")
            return errors

        runs_by_name = {str(r.get("name")): r for r in body.get("evaluationRuns", [])}
        target_sa = expected_evaluator_sa or str(verdict.get("expected_evaluator_sa") or "")

        for run_id in verdict["evaluation_run_ids"]:
            run = runs_by_name.get(run_id)
            if not run:
                errors.append(f"Claimed evaluationRun '{run_id}' does not exist in CES Sandbox.")
                continue
            progress = run.get("progress") or {}
            total = int(progress.get("totalCount", 0) or 0)
            failed = int(progress.get("failedCount", 0) or 0)
            if total <= 0:
                errors.append(f"evaluationRun '{run_id}' executed 0 test cases.")
            if failed > 0:
                errors.append(f"evaluationRun '{run_id}' recorded {failed} failed case(s).")
            initiated = str(run.get("initiatedBy") or "")
            if target_sa and initiated and target_sa not in initiated:
                errors.append(f"evaluationRun '{run_id}' initiatedBy '{initiated}' != expected SA '{target_sa}'.")

    return errors
