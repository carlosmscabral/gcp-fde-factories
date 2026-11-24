"""Deterministic 0-token closed-loop Kaizen proposal verifier (v0.4.0).

Tracks proposals from `proposed` through `implemented` (auto-detected via `Kaizen-Ref: <id>`
in merged PR titles, bodies, or commit messages) and `measuring` into `verified_pass`,
`rollback_triggered`, or `invalidated_regression` (anti-reward-hacking quality guard).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import tempfile
from typing import Any

from scripts.lib.schema_validator import validate_against_schema

KAIZEN_REF_RE = re.compile(r"Kaizen-Ref:\s*(KZ-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2,})", re.I)
VALID_OPERATORS = frozenset({"<=", ">=", "<", ">"})
ANTI_HACK_MIN_VERDICTS = 2
ANTI_HACK_TOLERANCE = 0.05


def _safe_int(value: Any, default: int = 0) -> int:
    """Converts a numeric or string value to an integer without raising exceptions."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso(raw: Any) -> dt.datetime | None:
    """Parses an ISO-8601 timestamp string and normalizes naive values to UTC."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _compare(measured: float, op: str, target: float) -> bool | None:
    """Evaluates a supported rollback predicate, returning None on unknown operators."""
    if op == "<=":
        return measured <= target
    if op == ">=":
        return measured >= target
    if op == "<":
        return measured < target
    if op == ">":
        return measured > target
    return None


def _default_proposal_schema() -> pathlib.Path | None:
    """Resolves schemas/kaizen-proposal.schema.json inside repo or /opt/gcp-fde."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    for cand in (
        repo_root / "schemas" / "kaizen-proposal.schema.json",
        pathlib.Path("/opt/gcp-fde/schemas/kaizen-proposal.schema.json"),
    ):
        if cand.is_file():
            return cand
    return None


def load_proposals(
    proposals_path: pathlib.Path | None,
    schema_path: pathlib.Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Loads, validates, and deduplicates append-only JSONL proposal records safely."""
    if not (proposals_path and proposals_path.is_file()):
        return [], []
    resolved_schema = schema_path or _default_proposal_schema()
    by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    try:
        lines = proposals_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"kaizen_verifier: unreadable {proposals_path.name}: {exc}"]

    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"kaizen_verifier: line {idx} invalid JSON: {exc}")
            continue
        if not isinstance(obj, dict) or not obj.get("proposal_id"):
            errors.append(f"kaizen_verifier: line {idx} missing proposal_id")
            continue
        if resolved_schema and resolved_schema.is_file():
            schema_errs = validate_against_schema(obj, resolved_schema)
            if schema_errs:
                errors.append(f"kaizen_verifier: line {idx} schema invalid: {schema_errs[0][:140]}")
                continue
        # Keep the latest state entry for each proposal_id in append-only logs.
        by_id[str(obj["proposal_id"])] = obj
    return list(by_id.values()), errors


def _pr_commit_messages(pr: dict[str, Any]) -> str:
    """Extracts commit headlines and bodies from GitHub CLI PR metadata."""
    commits = pr.get("commits")
    if not isinstance(commits, list):
        return ""
    parts: list[str] = []
    for commit in commits:
        if isinstance(commit, dict):
            parts.append(str(commit.get("messageHeadline") or ""))
            parts.append(str(commit.get("messageBody") or ""))
    return "\n".join(parts)


def _find_implementing_pr(proposal_id: str, merged_prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Finds the merged PR referencing `Kaizen-Ref: <proposal_id>` in title, body, or commits."""
    target = proposal_id.upper()
    for pr in merged_prs:
        text = f"{pr.get('title', '')}\n{pr.get('body', '')}\n{_pr_commit_messages(pr)}"
        if any(m.upper() == target for m in KAIZEN_REF_RE.findall(text)):
            return pr
    return None


def _compute_window_metrics(
    window_prs: list[dict[str, Any]],
    verdicts_by_pr: dict[int, str],
    hub_metrics: dict[str, Any],
    prior_snapshot: dict[str, Any] | None,
) -> tuple[dict[str, float | None], int]:
    """Computes objective post-merge metrics and verdict sample size across the PR window."""
    rounds: list[int] = []
    leads: list[float] = []
    live_hits = 0
    verdict_total = 0

    for pr in window_prs:
        created = _parse_iso(pr.get("createdAt"))
        merged = _parse_iso(pr.get("mergedAt"))
        if created and merged and merged >= created:
            leads.append((merged - created).total_seconds() / 3600.0)
        revs = pr.get("reviews") if isinstance(pr.get("reviews"), list) else []
        changes = sum(1 for r in revs if isinstance(r, dict) and str(r.get("state", "")).upper() == "CHANGES_REQUESTED")
        rounds.append(changes + (1 if revs else 0))

        pr_num = pr.get("number")
        if isinstance(pr_num, int) and pr_num in verdicts_by_pr:
            verdict_total += 1
            if verdicts_by_pr[pr_num] == "live-gcp-verified":
                live_hits += 1

    curr_tools = hub_metrics.get("tool_error_rates") or []
    curr_calls = sum(max(0, _safe_int(t.get("calls"))) for t in curr_tools if isinstance(t, dict))
    curr_errs = sum(max(0, _safe_int(t.get("errors"))) for t in curr_tools if isinstance(t, dict))

    # Avoid recycling cumulative errors when no new calls occurred since prior_snapshot.
    if isinstance(prior_snapshot, dict):
        prev_tools = (prior_snapshot.get("hub_metrics") or {}).get("tool_error_rates") or []
        prev_calls = sum(max(0, _safe_int(t.get("calls"))) for t in prev_tools if isinstance(t, dict))
        prev_errs = sum(max(0, _safe_int(t.get("errors"))) for t in prev_tools if isinstance(t, dict))
        if curr_calls > prev_calls:
            delta_calls = curr_calls - prev_calls
            delta_errs = max(0, curr_errs - prev_errs)
        elif curr_calls == prev_calls:
            delta_calls, delta_errs = 0, 0
        else:
            # Handle Hub counter resets cleanly by treating current totals as the fresh period.
            delta_calls, delta_errs = curr_calls, curr_errs
    else:
        delta_calls, delta_errs = curr_calls, curr_errs

    tool_rate = round(min(1.0, delta_errs / delta_calls), 4) if delta_calls > 0 else None
    metrics = {
        "avg_review_rounds": round(sum(rounds) / len(rounds), 2) if rounds else None,
        "avg_lead_time_hours": round(sum(leads) / len(leads), 2) if leads else None,
        "live_gcp_verified_rate": round(live_hits / verdict_total, 4) if verdict_total > 0 else None,
        "tool_error_rate": tool_rate,
    }
    return metrics, verdict_total


def load_latest_prior_snapshot(history_dir: pathlib.Path | None, current_date: str) -> dict[str, Any] | None:
    """Loads the most recent dated snapshot prior to current_date for cumulative metric deltas."""
    if not (history_dir and history_dir.is_dir()):
        return None
    candidates = sorted(p for p in history_dir.glob("*.json") if p.stem < current_date)
    if not candidates:
        return None
    try:
        data = json.loads(candidates[-1].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_proposal_state(state_path: pathlib.Path, verifications: list[dict[str, Any]]) -> None:
    """Persists latest proposal verification states atomically via temp file and os.replace."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"schema_version": "1", "proposals": verifications}, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(state_path.parent), prefix=".proposals-state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, state_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _resolve_baseline_live_rate(prop: dict[str, Any], prior_snapshot: dict[str, Any] | None) -> float | None:
    """Returns baseline live-gcp-verified rate from proposal or prior snapshot."""
    base_live = prop.get("baseline_live_gcp_rate")
    if base_live is not None:
        return float(base_live)
    if isinstance(prior_snapshot, dict):
        prev_vc = (prior_snapshot.get("scratchpad") or {}).get("verdict_counts") or {}
        prev_tot = sum(max(0, _safe_int(v)) for k, v in prev_vc.items() if k != "invalid")
        if prev_tot >= ANTI_HACK_MIN_VERDICTS:
            return round(max(0, _safe_int(prev_vc.get("live-gcp-verified"))) / prev_tot, 4)
    return None


def verify_proposals(
    proposals: list[dict[str, Any]],
    merged_prs: list[dict[str, Any]],
    verdicts_by_pr: dict[int, str],
    hub_metrics: dict[str, Any],
    prior_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluates Kaizen proposals across post-merge PR windows and detects regressions or rollbacks."""
    results: list[dict[str, Any]] = []
    pr_by_num = {pr.get("number"): pr for pr in merged_prs if isinstance(pr, dict) and isinstance(pr.get("number"), int)}

    for prop in proposals:
        pid = str(prop.get("proposal_id") or "unknown")
        rb = prop.get("rollback_criterion")
        if not isinstance(rb, dict) or _safe_int(rb.get("window_merged_prs")) < 1:
            results.append({
                "proposal_id": pid,
                "status": "rejected",
                "prs_observed": 0,
                "window_required": 1,
                "measured_value": None,
                "revert_command": None,
                "reason": "Malformed rollback_criterion in proposal record.",
            })
            continue
        window_req = _safe_int(rb.get("window_merged_prs"), 1)
        operator = str(rb.get("operator") or "")
        if operator not in VALID_OPERATORS:
            results.append({
                "proposal_id": pid,
                "status": "rejected",
                "prs_observed": 0,
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Unsupported rollback operator '{operator}'.",
            })
            continue

        status = str(prop.get("status") or "proposed")
        if status in ("verified_pass", "rollback_triggered", "invalidated_regression", "rejected"):
            results.append({
                "proposal_id": pid,
                "status": status,
                "prs_observed": 0,
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Terminal state '{status}' recorded.",
            })
            continue

        merged_at_raw = prop.get("merged_at_utc")
        merge_sha = prop.get("merge_commit_sha")
        impl_pr = prop.get("implemented_pr_number")
        if status == "proposed":
            hit = _find_implementing_pr(pid, merged_prs)
            if not hit:
                results.append({
                    "proposal_id": pid,
                    "status": "proposed",
                    "prs_observed": 0,
                    "window_required": window_req,
                    "measured_value": None,
                    "revert_command": None,
                    "reason": "Awaiting merged PR referencing Kaizen-Ref trailer.",
                })
                continue
            status = "implemented"
            impl_pr = hit.get("number")
            merged_at_raw = hit.get("mergedAt")
            mc = hit.get("mergeCommit")
            merge_sha = mc.get("oid") if isinstance(mc, dict) else merge_sha

        merged_dt = _parse_iso(merged_at_raw)
        if merged_dt is None and isinstance(impl_pr, int) and impl_pr in pr_by_num:
            merged_dt = _parse_iso(pr_by_num[impl_pr].get("mergedAt"))
        if merged_dt is None:
            results.append({
                "proposal_id": pid,
                "status": "measuring",
                "implemented_pr_number": impl_pr if isinstance(impl_pr, int) else None,
                "prs_observed": 0,
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": "Missing merged_at_utc timestamp. Cannot bound post-merge PR window.",
            })
            continue

        post_prs_pairs: list[tuple[dt.datetime, dict[str, Any]]] = []
        for pr in merged_prs:
            pr_dt = _parse_iso(pr.get("mergedAt"))
            if pr_dt is not None and pr_dt > merged_dt and pr.get("number") != impl_pr:
                post_prs_pairs.append((pr_dt, pr))
        post_prs_pairs.sort(key=lambda pair: pair[0])
        post_prs = [pair[1] for pair in post_prs_pairs]

        if len(post_prs) < window_req:
            results.append({
                "proposal_id": pid,
                "status": "measuring",
                "implemented_pr_number": impl_pr if isinstance(impl_pr, int) else None,
                "prs_observed": len(post_prs),
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Collected {len(post_prs)}/{window_req} post-merge PRs.",
            })
            continue

        window_slice = post_prs[:window_req]
        metrics, verdict_total = _compute_window_metrics(window_slice, verdicts_by_pr, hub_metrics, prior_snapshot)
        metric_name = str(prop.get("target_metric") or "")
        measured = metrics.get(metric_name)
        revert_target = str(rb.get("revert_target") or "proposal")
        revert_cmd = f"git revert {merge_sha}" if merge_sha else f"git revert <commit-for-{revert_target}>"

        base_live = _resolve_baseline_live_rate(prop, prior_snapshot)
        curr_live = metrics.get("live_gcp_verified_rate")
        if (
            base_live is not None
            and curr_live is not None
            and verdict_total >= ANTI_HACK_MIN_VERDICTS
            and curr_live < (base_live - ANTI_HACK_TOLERANCE)
        ):
            results.append({
                "proposal_id": pid,
                "status": "invalidated_regression",
                "implemented_pr_number": impl_pr if isinstance(impl_pr, int) else None,
                "prs_observed": len(window_slice),
                "window_required": window_req,
                "measured_value": measured,
                "revert_command": revert_cmd,
                "reason": f"Anti-reward-hacking guard triggered: live_gcp_verified_rate dropped {base_live} -> {curr_live}.",
            })
            continue

        if measured is None:
            results.append({
                "proposal_id": pid,
                "status": "measuring",
                "implemented_pr_number": impl_pr if isinstance(impl_pr, int) else None,
                "prs_observed": len(window_slice),
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Metric '{metric_name}' unavailable for observed PR window.",
            })
            continue

        target_val = float(rb["target_value"])
        passed = _compare(measured, operator, target_val)
        results.append({
            "proposal_id": pid,
            "status": "verified_pass" if passed else "rollback_triggered",
            "implemented_pr_number": impl_pr if isinstance(impl_pr, int) else None,
            "prs_observed": len(window_slice),
            "window_required": window_req,
            "measured_value": measured,
            "revert_command": None if passed else revert_cmd,
            "reason": (
                f"{metric_name}={measured} satisfied {operator} {target_val}."
                if passed
                else f"{metric_name}={measured} failed {operator} {target_val}."
            ),
        })
    return results
