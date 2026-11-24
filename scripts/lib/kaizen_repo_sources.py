"""Repository-local and GitHub telemetry adapters for the 0-token Kaizen collector (v0.3.0).

Collects merged PR review rounds, lead times, CI failures, hygiene issues, validated Verdict counts,
per-PR verdicts, scratchpad ledger/events, modernization backlog counts, and expiring workarounds.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any, Callable
from zoneinfo import ZoneInfo

import yaml

RunCmdFn = Callable[[list[str], pathlib.Path | None], tuple[int, str, str]]

ALLOWED_VERDICTS = frozenset({
    "live-gcp-verified",
    "not-verifiable-in-sandbox",
    "unit-test-verified",
    "static-check-only",
    "verifier-blocked",
    "verifier-failed",
})


def clean_token_str(raw: Any, max_len: int = 80) -> str:
    """Normalizes an external string to a single line with bounded length."""
    return " ".join(str(raw or "").split())[:max_len]


def _parse_iso(raw: Any) -> dt.datetime | None:
    """Parses an ISO-8601 UTC timestamp string into an aware datetime."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect_github_ci(
    repo_dir: pathlib.Path | None,
    run_cmd: RunCmdFn,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[str]]:
    """Collects merged PR review rounds, lead times, CI failures, hygiene issues, and PR metadata."""
    empty = {
        "merged_prs": 0,
        "avg_review_rounds": None,
        "avg_lead_time_hours": None,
        "failed_ci_runs": 0,
        "hygiene_issues_open": 0,
    }
    if not (repo_dir and repo_dir.exists()):
        return "skipped", empty, [], []

    rc, pr_out, err = run_cmd(
        [
            "gh", "pr", "list", "--state", "merged", "--limit", "25",
            "--json", "number,title,body,createdAt,mergedAt,mergeCommit,reviews",
        ],
        repo_dir,
    )
    if rc == 127:
        return "skipped", empty, [], []
    if rc != 0:
        return "error", empty, [], [f"github_ci: gh pr list failed (rc={rc}): {clean_token_str(err, 120)}"]

    try:
        prs = json.loads(pr_out)
    except json.JSONDecodeError:
        return "error", empty, [], ["github_ci: invalid JSON from gh pr list"]
    if not isinstance(prs, list):
        return "error", empty, [], ["github_ci: expected JSON array from gh pr list"]

    valid_prs = [pr for pr in prs if isinstance(pr, dict)]
    lead_hours: list[float] = []
    review_rounds: list[int] = []
    for pr in valid_prs:
        created = _parse_iso(pr.get("createdAt"))
        merged = _parse_iso(pr.get("mergedAt"))
        if created and merged and merged >= created:
            lead_hours.append((merged - created).total_seconds() / 3600.0)
        reviews = pr.get("reviews") if isinstance(pr.get("reviews"), list) else []
        changes = sum(1 for r in reviews if isinstance(r, dict) and str(r.get("state", "")).upper() == "CHANGES_REQUESTED")
        review_rounds.append(changes + (1 if reviews else 0))

    failed_runs = 0
    rc_run, run_out, _ = run_cmd(["gh", "run", "list", "--limit", "30", "--json", "conclusion"], repo_dir)
    if rc_run == 0:
        try:
            runs = json.loads(run_out)
            if isinstance(runs, list):
                failed_runs = sum(1 for r in runs if isinstance(r, dict) and str(r.get("conclusion", "")).lower() == "failure")
        except json.JSONDecodeError:
            pass

    hygiene_open = 0
    rc_iss, iss_out, _ = run_cmd(
        ["gh", "issue", "list", "--state", "open", "--label", "priority:hygiene", "--json", "number"],
        repo_dir,
    )
    if rc_iss == 0:
        try:
            issues = json.loads(iss_out)
            if isinstance(issues, list):
                hygiene_open = len(issues)
        except json.JSONDecodeError:
            pass

    return "ok", {
        "merged_prs": len(valid_prs),
        "avg_review_rounds": round(sum(review_rounds) / len(review_rounds), 2) if review_rounds else None,
        "avg_lead_time_hours": round(sum(lead_hours) / len(lead_hours), 2) if lead_hours else None,
        "failed_ci_runs": failed_runs,
        "hygiene_issues_open": hygiene_open,
    }, valid_prs, []


def collect_scratchpad(
    scratchpad_dir: pathlib.Path | None,
    verdicts_dir: pathlib.Path | None,
    workarounds_path: pathlib.Path | None,
    backlog_path: pathlib.Path | None = None,
    today: dt.date | None = None,
    time_zone: str = "America/Sao_Paulo",
    expiring_window_days: int = 15,
) -> tuple[str, dict[str, Any], dict[int, str], list[str]]:
    """Aggregates validated Verdict counts, per-PR verdicts, ledger/events, backlog gaps, and workarounds."""
    ref_day = today or dt.datetime.now(ZoneInfo(time_zone)).date()
    verdict_counts: dict[str, int] = {}
    verdicts_by_pr: dict[int, str] = {}
    seen_verdict_keys: set[str] = set()
    ledger_count = 0
    events_count = 0
    backlog_open = 0
    errors: list[str] = []
    files_read = 0

    verdict_files: list[pathlib.Path] = []
    if verdicts_dir and verdicts_dir.is_dir():
        verdict_files.extend(sorted(verdicts_dir.glob("pr-*.json")))
    if scratchpad_dir and scratchpad_dir.is_dir():
        verdict_files.extend(sorted(scratchpad_dir.rglob("*verdict*.json")))

    for vf in verdict_files:
        files_read += 1
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            verdict_counts["invalid"] = verdict_counts.get("invalid", 0) + 1
            errors.append(f"scratchpad: malformed verdict {vf.name}: {clean_token_str(exc, 100)}")
            continue
        if not isinstance(data, dict):
            verdict_counts["invalid"] = verdict_counts.get("invalid", 0) + 1
            errors.append(f"scratchpad: verdict {vf.name} is not a JSON object")
            continue
        dedup_key = f"{data.get('pr_number', vf.name)}:{data.get('commit_sha', '')}"
        if dedup_key in seen_verdict_keys:
            continue
        seen_verdict_keys.add(dedup_key)
        lvl = str(data.get("verdict", ""))
        bucket = lvl if lvl in ALLOWED_VERDICTS else "invalid"
        verdict_counts[bucket] = verdict_counts.get(bucket, 0) + 1
        if isinstance(data.get("pr_number"), int) and bucket != "invalid":
            verdicts_by_pr[int(data["pr_number"])] = bucket

    if scratchpad_dir and scratchpad_dir.is_dir():
        for fname, target in (("sandbox-ledger.jsonl", "ledger"), ("kaizen-events.jsonl", "events")):
            fpath = scratchpad_dir / fname
            if fpath.is_file():
                files_read += 1
                try:
                    count = sum(1 for ln in fpath.read_text(encoding="utf-8").splitlines() if ln.strip())
                    if target == "ledger":
                        ledger_count = count
                    else:
                        events_count = count
                except (OSError, UnicodeDecodeError) as exc:
                    errors.append(f"scratchpad: unreadable {fname}: {clean_token_str(exc, 100)}")

    if backlog_path and backlog_path.is_file():
        files_read += 1
        try:
            bdata = yaml.safe_load(backlog_path.read_text(encoding="utf-8"))
            if isinstance(bdata, dict) and isinstance(bdata.get("gaps"), list):
                backlog_open = sum(1 for g in bdata["gaps"] if isinstance(g, dict) and g.get("status", "open") == "open")
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            errors.append(f"scratchpad: malformed modernization-backlog.yaml: {clean_token_str(exc, 100)}")

    expiring: list[dict[str, Any]] = []
    if workarounds_path and workarounds_path.is_file():
        files_read += 1
        try:
            cfg = yaml.safe_load(workarounds_path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("WORKAROUNDS.yaml root must be a mapping")
            for item in cfg.get("workarounds") or []:
                if not isinstance(item, dict) or "expires_date" not in item:
                    raise ValueError("workaround entry missing expires_date")
                expires = dt.date.fromisoformat(str(item["expires_date"]))
                remaining = (expires - ref_day).days
                if remaining <= expiring_window_days:
                    expiring.append({
                        "id": clean_token_str(item.get("id", "unknown"), 40),
                        "component": clean_token_str(item.get("component", "unknown"), 64),
                        "days_remaining": remaining,
                    })
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"scratchpad: invalid WORKAROUNDS.yaml: {clean_token_str(exc, 100)}")

    status = "error" if (errors and files_read == len(errors)) else ("ok" if files_read > 0 else "skipped")
    return status, {
        "verdict_counts": verdict_counts,
        "sandbox_ledger_entries": ledger_count,
        "kaizen_events_count": events_count,
        "backlog_open_count": backlog_open,
        "workarounds_expiring_soon": expiring,
    }, verdicts_by_pr, errors
