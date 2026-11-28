"""Pure deterministic intake filtering and coordinator wakeup policy.

Evaluates explicit PO opt-in, veto and pause gates, dependency satisfaction, SEP
portfolio concurrency caps, and anti-echo comment/PR rules at zero LLM tokens.
"""
from __future__ import annotations

import re
from typing import Any

from adapters.base import CommentEvent, PullRequestEvent, WorkItem
from intake_models import (
    DEFAULT_BOT_LOGINS,
    IntakePolicy,
    TickDecision,
    WakeupEvent,
    WatcherState,
    sanitize_untrusted_text,
)

DEPENDS_ON_RE = re.compile(r"\bdepends\s+on\s+#(\d+)\b", re.IGNORECASE)
WAVE_LABEL_RE = re.compile(r"^wave[-_:]?(\d+)$", re.IGNORECASE)
PRIORITY_RANK = {
    "priority:p0": 0,
    "priority:critical": 0,
    "priority:p1": 1,
    "priority:high": 1,
    "priority:p2": 2,
    "priority:medium": 2,
    "priority:p3": 3,
    "priority:low": 3,
}

__all__ = [
    "DEFAULT_BOT_LOGINS",
    "IntakePolicy",
    "TickDecision",
    "WakeupEvent",
    "WatcherState",
    "evaluate_tick",
    "parse_dependencies",
    "sanitize_untrusted_text",
]


def _is_trusted_association(author_association: str, policy: IntakePolicy) -> bool:
    """Allows trusted repo roles and rejects untrusted drive-by actors on public or inner-source repos."""
    assoc = author_association.strip().upper()
    if not assoc:
        return True
    allowed = {a.strip().upper() for a in policy.allowed_author_associations if a.strip()}
    return assoc in allowed


def parse_dependencies(body: str) -> set[int]:
    """Extracts all referenced work item numbers from 'Depends on #N' clauses."""
    return {int(match.group(1)) for match in DEPENDS_ON_RE.finditer(body or "")}


def _priority_sort_key(item: WorkItem) -> tuple[int, int, int]:
    """Orders eligible items deterministically by priority label, wave label, then ID."""
    lowered = [lbl.strip().lower() for lbl in item.labels]
    prio = min((PRIORITY_RANK[lbl] for lbl in lowered if lbl in PRIORITY_RANK), default=99)
    wave_nums = [int(m.group(1)) for lbl in lowered if (m := WAVE_LABEL_RE.match(lbl))]
    wave = min(wave_nums) if wave_nums else 999
    return (prio, wave, item.number)


def _is_echo_comment(comment: CommentEvent, policy: IntakePolicy) -> bool:
    """Returns True when a comment originates from a bot or carries the anti-echo marker."""
    author = comment.author.strip().lower()
    if not author or author.endswith("[bot]"):
        return True
    if author in {b.strip().lower() for b in policy.bot_logins}:
        return True
    return bool(policy.echo_marker and policy.echo_marker in (comment.body or ""))


def evaluate_tick(
    policy: IntakePolicy,
    state: WatcherState,
    open_items: list[WorkItem],
    comments: list[CommentEvent],
    open_prs: list[PullRequestEvent],
    closed_dependency_numbers: set[int] | None = None,
) -> TickDecision:
    """Evaluates tracker snapshots against IntakePolicy and returns wakeup events and next state."""
    closed_deps = set(closed_dependency_numbers or set())
    open_by_num = {item.number: item for item in open_items}
    skipped: dict[str, int] = {}

    def _bump(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    # Retain only dispatched issues that remain open so closed issues release capacity slots.
    active_dispatched: dict[str, dict[str, Any]] = {
        k: dict(v)
        for k, v in state.dispatched_issues.items()
        if k.isdigit() and int(k) in open_by_num
    }
    seen_comment_set = set(state.seen_comment_ids)
    next_seen_comments = list(state.seen_comment_ids)
    open_pr_nums = {str(pr.number) for pr in open_prs}
    next_pr_signals = {k: v for k, v in state.seen_pr_signals.items() if k in open_pr_nums}
    events: list[WakeupEvent] = []
    dispatched_now: list[int] = []

    if not policy.enabled:
        return TickDecision(
            events=[],
            next_state=WatcherState(active_dispatched, next_seen_comments, next_pr_signals),
            metrics={
                "scanned_items": len(open_items),
                "eligible_items": 0,
                "dispatched_ids": [],
                "skipped_reasons": {"intake_disabled": len(open_items)},
                "active_dispatched": sorted(int(k) for k in active_dispatched),
            },
        )

    # 1. Select newly eligible open issues under default-deny opt-in, veto, and dependency gates.
    release_lbl = policy.release_label.strip().lower()
    hold_lbl = policy.hold_label.strip().lower()
    scope_lbl = policy.scope_label.strip().lower()
    candidates: list[WorkItem] = []

    for item in open_items:
        if str(item.number) in active_dispatched:
            continue
        lowered = {lbl.strip().lower() for lbl in item.labels}
        if release_lbl not in lowered:
            _bump("missing_release_label")
            continue
        if scope_lbl and scope_lbl not in lowered:
            _bump("missing_scope_label")
            continue
        if hold_lbl in lowered or "wontfix" in lowered:
            _bump("held_or_wontfix")
            continue
        if any(dep in open_by_num or dep not in closed_deps for dep in parse_dependencies(item.body)):
            _bump("unmet_dependency")
            continue
        candidates.append(item)

    candidates.sort(key=_priority_sort_key)
    cap = policy.normalized_capacity()
    for item in candidates:
        if policy.paused:
            _bump("paused")
            continue
        if len(active_dispatched) >= cap:
            _bump("capacity_full")
            continue
        active_dispatched[str(item.number)] = {
            "title": item.title,
            "url": item.url,
            "updated_at": item.updated_at,
        }
        dispatched_now.append(item.number)
        clean_title = sanitize_untrusted_text(item.title)
        events.append(
            WakeupEvent(
                kind="new_issue",
                issue_number=item.number,
                pr_number=None,
                title=clean_title,
                url=item.url,
                summary=f"Newly eligible issue #{item.number}: {clean_title}",
                author=item.author,
            )
        )

    active_nums = {int(k) for k in active_dispatched}
    newly_dispatched_set = set(dispatched_now)

    # 2. Seed pre-existing comments on newly dispatched issues and forward new human replies on active issues.
    for comment in comments:
        if comment.item_number not in active_nums or comment.id in seen_comment_set:
            continue
        seen_comment_set.add(comment.id)
        next_seen_comments.append(comment.id)
        if comment.item_number in newly_dispatched_set:
            continue
        if _is_echo_comment(comment, policy):
            _bump("bot_or_echo_comment")
            continue
        if not _is_trusted_association(comment.author_association, policy):
            _bump("untrusted_author_association")
            continue
        snippet = sanitize_untrusted_text(comment.body)[:180]
        events.append(
            WakeupEvent(
                kind="human_comment",
                issue_number=comment.item_number,
                pr_number=None,
                title=sanitize_untrusted_text(open_by_num[comment.item_number].title),
                url=comment.url,
                summary=f"Human comment by @{comment.author} on {comment.target_kind} for #{comment.item_number}: {snippet}",
                author=comment.author,
            )
        )

    # 3. Forward actionable linked PR signals from trusted PR authors only (CI/Verdict failure or Changes Requested).
    for pr in open_prs:
        linked_active = sorted(n for n in pr.linked_issue_numbers if n in active_nums)
        if not linked_active:
            continue
        if not _is_trusted_association(pr.author_association, policy):
            _bump("untrusted_pr_author")
            continue
        needs_ci = pr.checks_state.upper() in ("FAILURE", "ERROR")
        needs_review = pr.review_decision.upper() == "CHANGES_REQUESTED"
        if not (needs_ci or needs_review):
            continue
        signal = f"{pr.checks_state.upper()}|{pr.review_decision.upper()}|{pr.updated_at}"
        pr_key = str(pr.number)
        if next_pr_signals.get(pr_key) == signal:
            _bump("unchanged_pr_signal")
            continue
        next_pr_signals[pr_key] = signal
        reasons = [r for r in (f"checks={pr.checks_state.upper()}" if needs_ci else "", "review=CHANGES_REQUESTED" if needs_review else "") if r]
        clean_pr_title = sanitize_untrusted_text(pr.title)
        events.append(
            WakeupEvent(
                kind="pr_action_needed",
                issue_number=linked_active[0],
                pr_number=pr.number,
                title=clean_pr_title,
                url=pr.url,
                summary=f"PR #{pr.number} ({', '.join(reasons)}) for issue #{linked_active[0]}: {clean_pr_title}",
                author=pr.author,
            )
        )

    return TickDecision(
        events=events,
        next_state=WatcherState(active_dispatched, next_seen_comments, next_pr_signals),
        metrics={
            "scanned_items": len(open_items),
            "eligible_items": len(candidates),
            "dispatched_ids": dispatched_now,
            "skipped_reasons": skipped,
            "active_dispatched": sorted(active_nums),
        },
    )
