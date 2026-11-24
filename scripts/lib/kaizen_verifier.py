"""Deterministic 0-token closed-loop Kaizen proposal verifier (v0.3.0).

Tracks proposals from `proposed` through `implemented` (auto-detected via `Kaizen-Ref: <id>`
in merged PR metadata or git trailers) and `measuring` into `verified_pass`,
`rollback_triggered`, or `invalidated_regression` (anti-reward-hacking quality guard).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from typing import Any

KAIZEN_REF_RE = re.compile(r"Kaizen-Ref:\s*(KZ-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2,})", re.I)


def _parse_iso(raw: Any) -> dt.datetime | None:
    """Parses an ISO-8601 UTC timestamp string into an aware datetime."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compare(measured: float, op: str, target: float) -> bool:
    """Evaluates a machine-readable rollback threshold predicate."""
    if op == "<=":
        return measured <= target
    if op == ">=":
        return measured >= target
    if op == "<":
        return measured < target
    if op == ">":
        return measured > target
    return False


def load_proposals(proposals_path: pathlib.Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Loads proposal records from a JSONL registry file with safe error reporting."""
    if not (proposals_path and proposals_path.is_file()):
        return [], []
    proposals: list[dict[str, Any]] = []
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
            if isinstance(obj, dict) and obj.get("proposal_id"):
                proposals.append(obj)
            else:
                errors.append(f"kaizen_verifier: line {idx} missing proposal_id")
        except json.JSONDecodeError as exc:
            errors.append(f"kaizen_verifier: line {idx} invalid JSON: {exc}")
    return proposals, errors


def _find_implementing_pr(proposal_id: str, merged_prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Finds the merged PR referencing `Kaizen-Ref: <proposal_id>` in title or body."""
    for pr in merged_prs:
        text = f"{pr.get('title', '')}\n{pr.get('body', '')}"
        if any(m.upper() == proposal_id.upper() for m in KAIZEN_REF_RE.findall(text)):
            return pr
    return None


def _compute_window_metrics(
    window_prs: list[dict[str, Any]],
    verdicts_by_pr: dict[int, str],
    hub_metrics: dict[str, Any],
    prior_snapshot: dict[str, Any] | None,
) -> dict[str, float | None]:
    """Computes objective post-merge metrics strictly across PRs inside the evaluation window."""
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

    # Compute tool_error_rate as period delta when a prior dated snapshot exists, else current aggregate.
    curr_tools = hub_metrics.get("tool_error_rates") or []
    curr_calls = sum(int(t.get("calls", 0) or 0) for t in curr_tools if isinstance(t, dict))
    curr_errs = sum(int(t.get("errors", 0) or 0) for t in curr_tools if isinstance(t, dict))
    prev_calls = prev_errs = 0
    if isinstance(prior_snapshot, dict):
        prev_tools = (prior_snapshot.get("hub_metrics") or {}).get("tool_error_rates") or []
        prev_calls = sum(int(t.get("calls", 0) or 0) for t in prev_tools if isinstance(t, dict))
        prev_errs = sum(int(t.get("errors", 0) or 0) for t in prev_tools if isinstance(t, dict))
    delta_calls = curr_calls - prev_calls if curr_calls > prev_calls else curr_calls
    delta_errs = max(0, curr_errs - prev_errs) if curr_calls > prev_calls else curr_errs
    tool_rate = round(min(1.0, delta_errs / delta_calls), 4) if delta_calls > 0 else None

    return {
        "avg_review_rounds": round(sum(rounds) / len(rounds), 2) if rounds else None,
        "avg_lead_time_hours": round(sum(leads) / len(leads), 2) if leads else None,
        "live_gcp_verified_rate": round(live_hits / verdict_total, 4) if verdict_total > 0 else None,
        "tool_error_rate": tool_rate,
    }


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


def verify_proposals(
    proposals: list[dict[str, Any]],
    merged_prs: list[dict[str, Any]],
    verdicts_by_pr: dict[int, str],
    hub_metrics: dict[str, Any],
    prior_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluates Kaizen proposals across post-merge PR windows and detects regressions or rollbacks."""
    results: list[dict[str, Any]] = []
    for prop in proposals:
        pid = str(prop["proposal_id"])
        status = str(prop.get("status") or "proposed")
        if status in ("verified_pass", "rollback_triggered", "invalidated_regression", "rejected"):
            results.append({
                "proposal_id": pid,
                "status": status,
                "prs_observed": 0,
                "window_required": int(prop["rollback_criterion"]["window_merged_prs"]),
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
                    "window_required": int(prop["rollback_criterion"]["window_merged_prs"]),
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
        rb = prop["rollback_criterion"]
        window_req = int(rb["window_merged_prs"])
        post_prs = [
            pr for pr in merged_prs
            if (_parse_iso(pr.get("mergedAt")) is not None)
            and (merged_dt is None or _parse_iso(pr.get("mergedAt")) > merged_dt)  # type: ignore[operator]
            and pr.get("number") != impl_pr
        ]
        post_prs.sort(key=lambda p: str(p.get("mergedAt") or ""))

        if len(post_prs) < window_req:
            results.append({
                "proposal_id": pid,
                "status": "measuring",
                "implemented_pr_number": impl_pr,
                "prs_observed": len(post_prs),
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Collected {len(post_prs)}/{window_req} post-merge PRs.",
            })
            continue

        window_slice = post_prs[:window_req]
        metrics = _compute_window_metrics(window_slice, verdicts_by_pr, hub_metrics, prior_snapshot)
        metric_name = str(prop["target_metric"])
        measured = metrics.get(metric_name)
        revert_cmd = f"git revert {merge_sha}" if merge_sha else f"git revert <commit-for-{rb['revert_target']}>"

        # Anti-reward-hacking guard: invalidate if live-gcp-verified rate dropped below baseline.
        base_live = prop.get("baseline_live_gcp_rate")
        if base_live is None and isinstance(prior_snapshot, dict):
            prev_vc = (prior_snapshot.get("scratchpad") or {}).get("verdict_counts") or {}
            prev_tot = sum(int(v or 0) for k, v in prev_vc.items() if k != "invalid")
            if prev_tot > 0:
                base_live = round(int(prev_vc.get("live-gcp-verified", 0) or 0) / prev_tot, 4)
        curr_live = metrics.get("live_gcp_verified_rate")
        if base_live is not None and curr_live is not None and curr_live < float(base_live):
            results.append({
                "proposal_id": pid,
                "status": "invalidated_regression",
                "implemented_pr_number": impl_pr,
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
                "implemented_pr_number": impl_pr,
                "prs_observed": len(window_slice),
                "window_required": window_req,
                "measured_value": None,
                "revert_command": None,
                "reason": f"Metric '{metric_name}' unavailable for observed PR window.",
            })
            continue

        passed = _compare(measured, str(rb["operator"]), float(rb["target_value"]))
        results.append({
            "proposal_id": pid,
            "status": "verified_pass" if passed else "rollback_triggered",
            "implemented_pr_number": impl_pr,
            "prs_observed": len(window_slice),
            "window_required": window_req,
            "measured_value": measured,
            "revert_command": None if passed else revert_cmd,
            "reason": (
                f"{metric_name}={measured} satisfied {rb['operator']} {rb['target_value']}."
                if passed
                else f"{metric_name}={measured} failed {rb['operator']} {rb['target_value']}."
            ),
        })
    return results
