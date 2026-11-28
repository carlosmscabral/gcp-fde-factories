"""Policy, cursor state, and decision models for deterministic SEP intake filtering.

Kept free of network I/O and control-flow branching so intake_filter.py stays focused
strictly on pure policy evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_BOT_LOGINS = (
    "github-actions",
    "github-actions[bot]",
    "dependabot",
    "dependabot[bot]",
    "scion-bot",
    "scion-factory[bot]",
)
MAX_SEEN_COMMENT_IDS = 2000


@dataclass(frozen=True)
class IntakePolicy:
    """Declares deterministic intake filtering rules matching .factory/hub-project.yaml."""

    enabled: bool = True
    provider: str = "github"
    max_concurrent_issues: int = 2
    scope_label: str = ""
    release_label: str = "factory:ready"
    hold_label: str = "factory:hold"
    paused: bool = False
    bot_logins: tuple[str, ...] = DEFAULT_BOT_LOGINS
    echo_marker: str = "<!-- scion-factory -->"

    def normalized_capacity(self) -> int:
        """Clamps portfolio concurrency to the SEP empirical ceiling of 1 to 3 issues."""
        return max(1, min(3, int(self.max_concurrent_issues)))


@dataclass
class WatcherState:
    """Holds JSON-serializable cursor state persisted across Cloud Scheduler ticks."""

    dispatched_issues: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen_comment_ids: list[str] = field(default_factory=list)
    seen_pr_signals: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WatcherState:
        """Parses persisted cursor JSON into a WatcherState instance."""
        dispatched = raw.get("dispatched_issues")
        seen_comments = raw.get("seen_comment_ids")
        seen_prs = raw.get("seen_pr_signals")
        return cls(
            dispatched_issues=dict(dispatched) if isinstance(dispatched, dict) else {},
            seen_comment_ids=[str(c) for c in seen_comments] if isinstance(seen_comments, list) else [],
            seen_pr_signals={str(k): str(v) for k, v in seen_prs.items()} if isinstance(seen_prs, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializes state with bounded comment history for deterministic storage."""
        return {
            "dispatched_issues": dict(self.dispatched_issues),
            "seen_comment_ids": self.seen_comment_ids[-MAX_SEEN_COMMENT_IDS:],
            "seen_pr_signals": dict(self.seen_pr_signals),
        }


@dataclass(frozen=True)
class WakeupEvent:
    """Represents one actionable delta forwarded to the Scion Hub coordinator."""

    kind: str
    issue_number: int
    pr_number: int | None
    title: str
    url: str
    summary: str
    author: str = ""


@dataclass(frozen=True)
class TickDecision:
    """Carries the filtered wakeup events, updated cursor state, and structured metrics."""

    events: list[WakeupEvent]
    next_state: WatcherState
    metrics: dict[str, Any]
