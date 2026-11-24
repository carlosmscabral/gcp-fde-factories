"""Anti-forgery Verdict verification engine (Contract 5 — GECX and ADK packs).

Verifies JSON Schema conformance, pack match, commit SHA, evals/ tree SHA-256 integrity,
authorized not-verifiable surfaces, strict PR/commit displayName provenance binding,
and live Sandbox API checks (paginated CES evaluationRuns, Vertex AI ReasoningEngine,
and Discovery Engine Gemini Enterprise agents).
"""
from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from scripts.lib.io_utils import load_json, sha256_tree
from scripts.lib.schema_validator import validate_against_schema

FetchFn = Callable[[str, str, str], tuple[int, dict[str, Any]]]


def default_sandbox_get(url: str, access_token: str, quota_project: str) -> tuple[int, dict[str, Any]]:
    """Executes an authenticated REST GET against CES, Vertex AI, or Discovery Engine APIs."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": quota_project,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
        return code, {"error": str(exc)}


def _extract_project(resource_name: str) -> str:
    """Extracts the GCP project segment from a projects/<project>/... resource path."""
    parts = resource_name.split("/")
    if len(parts) >= 2 and parts[0] == "projects":
        return parts[1]
    return ""


def _list_ces_runs_paginated(
    base_url: str, access_token: str, sandbox_project: str, fetch_fn: FetchFn
) -> tuple[bool, list[dict[str, Any]], str]:
    """Fetches all pages of CES evaluationRuns under an ephemeral Sandbox app."""
    runs: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(20):
        url = f"{base_url}?pageToken={urllib.parse.quote(page_token)}" if page_token else base_url
        status, body = fetch_fn(url, access_token, sandbox_project)
        if status != 200:
            return False, [], f"CES API GET {url} returned HTTP {status}."
        runs.extend(body.get("evaluationRuns", []) or [])
        page_token = str(body.get("nextPageToken") or "")
        if not page_token:
            return True, runs, ""
    return True, runs, ""


def _verify_ces_runs(
    verdict: dict[str, Any],
    sandbox_project: str,
    expected_evaluator_sa: str,
    access_token: str,
    fetch_fn: FetchFn,
) -> list[str]:
    """Verifies ephemeral CES app PR/commit binding and paginated evaluationRuns."""
    errors: list[str] = []
    app_name = str(verdict.get("ephemeral_app_name") or "")
    if not app_name:
        return ["GECX live-gcp-verified requires non-empty ephemeral_app_name."]
    if _extract_project(app_name) != sandbox_project:
        return [f"CES app project '{_extract_project(app_name)}' != sandbox_project '{sandbox_project}'."]

    pr_tag = f"PR-{verdict['pr_number']}"
    sha7 = str(verdict["commit_sha"])[:7]
    app_url = f"https://ces.googleapis.com/v1beta/{app_name}"
    app_status, app_body = fetch_fn(app_url, access_token, sandbox_project)
    if app_status == 200 and isinstance(app_body, dict) and "displayName" in app_body:
        disp = str(app_body.get("displayName") or "")
        if pr_tag not in disp or sha7 not in disp:
            errors.append(f"CES app displayName '{disp}' is not bound to {pr_tag} and commit {sha7}.")
    elif app_status != 200:
        errors.append(f"CES app GET {app_url} failed provenance check (HTTP {app_status}).")

    ok, all_runs, err = _list_ces_runs_paginated(
        f"https://ces.googleapis.com/v1beta/{app_name}/evaluationRuns",
        access_token,
        sandbox_project,
        fetch_fn,
    )
    if not ok:
        errors.append(err)
        return errors

    runs_by_name = {r.get("name"): r for r in all_runs if isinstance(r, dict)}
    target_sa = expected_evaluator_sa or str(verdict.get("expected_evaluator_sa") or "")
    for run_id in verdict["evaluation_run_ids"]:
        run = runs_by_name.get(run_id)
        if not run:
            errors.append(f"Claimed evaluationRun '{run_id}' does not exist in CES Sandbox.")
            continue
        state = str(run.get("state") or "")
        if state and state.upper() not in ("SUCCEEDED", "COMPLETED", "STATE_UNSPECIFIED"):
            errors.append(f"evaluationRun '{run_id}' ended in state '{state}'.")
        prog = run.get("progress") or {}
        if int(prog.get("totalCount", 0) or 0) <= 0:
            errors.append(f"evaluationRun '{run_id}' executed 0 test cases.")
        if int(prog.get("failedCount", 0) or 0) > 0:
            errors.append(f"evaluationRun '{run_id}' recorded {prog['failedCount']} failed case(s).")
        initiated = str(run.get("initiatedBy") or "")
        if target_sa and initiated and target_sa not in initiated:
            errors.append(f"evaluationRun '{run_id}' initiatedBy '{initiated}' != expected SA '{target_sa}'.")
    return errors


def _verify_adk_live(
    verdict: dict[str, Any],
    sandbox_project: str,
    expected_evaluator_sa: str,
    access_token: str,
    fetch_fn: FetchFn,
) -> list[str]:
    """Verifies ADK Sandbox ReasoningEngine and Gemini Enterprise provenance bound to PR and commit."""
    errors: list[str] = []
    v_sa = str(verdict.get("expected_evaluator_sa") or "")
    if not v_sa:
        errors.append("ADK live-gcp-verified requires non-empty expected_evaluator_sa.")
    if expected_evaluator_sa and v_sa != expected_evaluator_sa:
        errors.append(f"Verdict expected_evaluator_sa '{v_sa}' != CI evaluator SA '{expected_evaluator_sa}'.")
    if "l2:adk-eval" not in (verdict.get("gates_executed") or []):
        errors.append("ADK live-gcp-verified requires 'l2:adk-eval' in gates_executed.")

    pr_tag = f"PR-{verdict['pr_number']}"
    sha7 = str(verdict["commit_sha"])[:7]
    app_name = str(verdict.get("ephemeral_app_name") or "")
    ge_agent = str(verdict.get("ge_agent_resource") or "")

    if app_name:
        if _extract_project(app_name) != sandbox_project:
            errors.append(f"ReasoningEngine project '{_extract_project(app_name)}' != sandbox_project '{sandbox_project}'.")
        else:
            loc = app_name.split("/locations/", 1)[1].split("/", 1)[0]
            url = f"https://{loc}-aiplatform.googleapis.com/v1beta1/{app_name}"
            status, body = fetch_fn(url, access_token, sandbox_project)
            if status != 200 or body.get("name") != app_name:
                errors.append(f"Vertex AI Agent Engine GET {url} failed verification (HTTP {status}).")
            else:
                disp = str(body.get("displayName") or "")
                if pr_tag not in disp or sha7 not in disp:
                    errors.append(f"ReasoningEngine displayName '{disp}' is not bound to {pr_tag} and commit {sha7}.")

    if ge_agent:
        if _extract_project(ge_agent) != sandbox_project:
            errors.append(f"Gemini Enterprise agent project '{_extract_project(ge_agent)}' != sandbox_project '{sandbox_project}'.")
        else:
            loc = ge_agent.split("/locations/", 1)[1].split("/", 1)[0]
            prefix = "" if loc == "global" else f"{loc}-"
            url = f"https://{prefix}discoveryengine.googleapis.com/v1alpha/{ge_agent}"
            status, body = fetch_fn(url, access_token, sandbox_project)
            if status != 200 or body.get("name") != ge_agent:
                errors.append(f"Gemini Enterprise GET {url} failed verification (HTTP {status}).")
            else:
                disp = str(body.get("displayName") or "")
                if "[CI]" not in disp or pr_tag not in disp or sha7 not in disp:
                    errors.append(
                        f"Gemini Enterprise agent displayName '{disp}' is not bound to [CI], {pr_tag}, and commit {sha7}."
                    )
    return errors


def verify_verdict(
    verdict_path: pathlib.Path,
    schema_path: pathlib.Path,
    expected_commit: str,
    evals_dir: pathlib.Path,
    sandbox_project: str = "",
    expected_evaluator_sa: str = "",
    access_token: str = "",
    fetch_fn: FetchFn = default_sandbox_get,
    expected_pack: str = "",
    expected_pr_number: int | None = None,
    allowed_surfaces: set[str] | None = None,
    require_live: bool = False,
) -> list[str]:
    """Verifies a Verdict file against schema, local git/evals integrity, policy, and live Sandbox APIs."""
    verdict = load_json(verdict_path)
    errors = validate_against_schema(verdict, schema_path)
    if errors:
        return errors

    verdict_pack = str(verdict.get("pack") or "gecx")
    if expected_pack and verdict_pack != expected_pack:
        errors.append(f"Verdict pack '{verdict_pack}' != expected pack '{expected_pack}'.")
    if expected_pr_number is not None and int(verdict["pr_number"]) != expected_pr_number:
        errors.append(f"Verdict pr_number {verdict['pr_number']} != expected PR #{expected_pr_number}.")
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

    if require_live and level != "live-gcp-verified":
        errors.append(f"CI requires 'live-gcp-verified', but verdict downgraded to '{level}'.")
        return errors

    if level == "not-verifiable-in-sandbox" and allowed_surfaces is not None:
        invalid = [s for s in verdict.get("not_verifiable_surfaces", []) if s not in allowed_surfaces]
        if invalid:
            errors.append(f"Unauthorized not_verifiable_surfaces: {invalid}. Allowed: {sorted(allowed_surfaces)}.")

    if level == "unit-test-verified" and not (verdict.get("gates_executed") or []):
        errors.append("unit-test-verified requires at least one executed test gate in gates_executed.")

    if level == "live-gcp-verified":
        if not access_token or not sandbox_project:
            errors.append("live-gcp-verified requires live Sandbox API verification with access_token and sandbox_project.")
            return errors
        if verdict_pack == "gecx":
            errors.extend(_verify_ces_runs(verdict, sandbox_project, expected_evaluator_sa, access_token, fetch_fn))
        elif verdict_pack == "adk":
            errors.extend(_verify_adk_live(verdict, sandbox_project, expected_evaluator_sa, access_token, fetch_fn))
        else:
            errors.append(f"Unsupported pack '{verdict_pack}' for live verification.")

    return errors
