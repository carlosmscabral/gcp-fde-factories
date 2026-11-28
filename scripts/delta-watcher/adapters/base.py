"""Normalized issue-tracker models and provider-agnostic adapter protocol.

Separates tracker-specific API payloads from deterministic SEP intake filtering so
GitHub, Azure DevOps, GitLab, and Jira adapters share one evaluation contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WorkItem:
    """Represents one normalized issue or work item from an external tracker."""

    id: str
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]
    author: str
    url: str
    updated_at: str
    author_association: str = ""


@dataclass(frozen=True)
class CommentEvent:
    """Represents one comment on an issue or linked pull request."""

    id: str
    item_number: int
    target_kind: str
    author: str
    body: str
    url: str
    created_at: str
    author_association: str = ""


@dataclass(frozen=True)
class PullRequestEvent:
    """Represents one open pull request linked to zero or more work items."""

    number: int
    title: str
    state: str
    author: str
    url: str
    updated_at: str
    linked_issue_numbers: tuple[int, ...]
    checks_state: str
    review_decision: str
    author_association: str = ""


class TrackerAdapter(Protocol):
    """Defines the read-only tracker contract consumed by the Delta Watcher loop."""

    def list_open_items(self) -> list[WorkItem]:
        """Returns all open issues or work items for the configured repository."""

    def list_comments(self, item_numbers: set[int]) -> list[CommentEvent]:
        """Returns comments for the tracked issue numbers and their linked pull requests."""

    def list_open_prs(self) -> list[PullRequestEvent]:
        """Returns open pull requests with check rollup and review decision metadata."""

    def get_closed_item_numbers(self, numbers: set[int]) -> set[int]:
        """Returns the subset of referenced work item numbers currently in a closed state."""
