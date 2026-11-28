"""GitHub GraphQL adapter for the External Delta Watcher.

Fetches open issues, linked pull requests, and recent comments via bounded GraphQL
queries to stay inside GitHub API rate limits without third-party HTTP dependencies.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from adapters.base import CommentEvent, PullRequestEvent, WorkItem
from adapters.github_queries import (
    OPEN_ISSUES_QUERY,
    OPEN_PRS_QUERY,
    build_closed_items_query,
    build_open_issues_by_numbers_query,
)

DEFAULT_GRAPHQL_URL = "https://api.github.com/graphql"
ISSUE_REF_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)", re.IGNORECASE)

HttpPostFn = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _default_http_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    """Posts a JSON request via stdlib urllib and decodes the JSON response."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {detail}") from exc


def _extract_linked_issues(pr_node: dict[str, Any]) -> tuple[int, ...]:
    """Collects linked issue numbers from closing references and PR body keywords."""
    refs: set[int] = set()
    closing = (pr_node.get("closingIssuesReferences") or {}).get("nodes") or []
    for node in closing:
        if isinstance(node, dict) and isinstance(node.get("number"), int):
            refs.add(node["number"])
    for match in ISSUE_REF_RE.finditer(str(pr_node.get("body") or "")):
        refs.add(int(match.group(1)))
    return tuple(sorted(refs))


def _extract_checks_state(pr_node: dict[str, Any]) -> str:
    """Extracts the latest commit statusCheckRollup state from a GitHub PR node."""
    commits = (pr_node.get("commits") or {}).get("nodes") or []
    if not commits:
        return "UNKNOWN"
    rollup = ((commits[-1] or {}).get("commit") or {}).get("statusCheckRollup") or {}
    return str(rollup.get("state") or "UNKNOWN").upper()


def _parse_comments(nodes: list[Any], item_number: int, target_kind: str) -> list[CommentEvent]:
    """Converts raw GraphQL comment nodes into normalized CommentEvent objects."""
    return [
        CommentEvent(
            id=str(c["id"]),
            item_number=item_number,
            target_kind=target_kind,
            author=str(((c.get("author") or {}).get("login")) or ""),
            body=str(c.get("body") or ""),
            url=str(c.get("url") or ""),
            created_at=str(c.get("createdAt") or ""),
            author_association=str(c.get("authorAssociation") or "").upper(),
        )
        for c in nodes
        if isinstance(c, dict) and c.get("id")
    ]


def _parse_issue_node(node: dict[str, Any]) -> tuple[WorkItem, list[CommentEvent]]:
    """Normalizes one GraphQL Issue node into a WorkItem and its recent CommentEvent list."""
    num = int(node["number"])
    labels = tuple(
        str(lbl["name"])
        for lbl in ((node.get("labels") or {}).get("nodes") or [])
        if isinstance(lbl, dict) and lbl.get("name")
    )
    item = WorkItem(
        id=str(node.get("id") or f"issue-{num}"),
        number=num,
        title=str(node.get("title") or ""),
        body=str(node.get("body") or ""),
        state=str(node.get("state") or "OPEN").upper(),
        labels=labels,
        author=str(((node.get("author") or {}).get("login")) or ""),
        url=str(node.get("url") or ""),
        updated_at=str(node.get("updatedAt") or ""),
        author_association=str(node.get("authorAssociation") or "").upper(),
    )
    comments = _parse_comments((node.get("comments") or {}).get("nodes") or [], num, "issue")
    return item, comments


class GitHubTrackerAdapter:
    """Implements TrackerAdapter against GitHub GraphQL with bounded pagination."""

    def __init__(
        self,
        repo_slug: str,
        token: str | None = None,
        api_url: str = DEFAULT_GRAPHQL_URL,
        max_pages: int = 5,
        timeout: float = 20.0,
        http_post: HttpPostFn | None = None,
        filter_labels: tuple[str, ...] = (),
    ) -> None:
        parts = repo_slug.strip().split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid GitHub repository slug: '{repo_slug}'. Expected 'owner/repo'.")
        self._owner, self._name = parts[0], parts[1]
        self._token = token
        self._api_url = api_url
        self._max_pages = max(1, max_pages)
        self._timeout = timeout
        self._http_post = http_post or _default_http_post
        self._filter_labels = tuple(lbl.strip() for lbl in filter_labels if lbl and lbl.strip())
        self._cached_issue_comments: dict[int, list[CommentEvent]] = {}
        self._cached_pr_comments: dict[int, list[CommentEvent]] = {}

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Executes one GraphQL query using the configured or environment token."""
        token = self._token if self._token is not None else os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise RuntimeError("Missing GITHUB_TOKEN for GitHubTrackerAdapter.")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "gcp-fde-factories-delta-watcher",
        }
        data = self._http_post(self._api_url, {"query": query, "variables": variables}, headers, self._timeout)
        if data.get("errors"):
            raise RuntimeError(f"GitHub GraphQL error: {data['errors'][0]}")
        return data.get("data") or {}

    def list_open_items(self) -> list[WorkItem]:
        """Fetches open issues and caches their recent comments to avoid duplicate queries."""
        items: list[WorkItem] = []
        self._cached_issue_comments.clear()
        cursor: str | None = None
        for _ in range(self._max_pages):
            variables: dict[str, Any] = {
                "owner": self._owner,
                "name": self._name,
                "cursor": cursor,
                "labels": list(self._filter_labels) or None,
            }
            data = self._graphql(OPEN_ISSUES_QUERY, variables)
            conn = (data.get("repository") or {}).get("issues") or {}
            for node in conn.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                item, node_comments = _parse_issue_node(node)
                items.append(item)
                self._cached_issue_comments[item.number] = node_comments
            page = conn.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            cursor = str(page["endCursor"])
        return items

    def list_open_prs(self) -> list[PullRequestEvent]:
        """Fetches open pull requests and caches their recent comments by linked issue."""
        prs: list[PullRequestEvent] = []
        self._cached_pr_comments.clear()
        cursor: str | None = None
        for _ in range(self._max_pages):
            data = self._graphql(OPEN_PRS_QUERY, {"owner": self._owner, "name": self._name, "cursor": cursor})
            conn = (data.get("repository") or {}).get("pullRequests") or {}
            for node in conn.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                pr_num = int(node["number"])
                linked = _extract_linked_issues(node)
                prs.append(
                    PullRequestEvent(
                        number=pr_num,
                        title=str(node.get("title") or ""),
                        state=str(node.get("state") or "OPEN").upper(),
                        author=str(((node.get("author") or {}).get("login")) or ""),
                        url=str(node.get("url") or ""),
                        updated_at=str(node.get("updatedAt") or ""),
                        linked_issue_numbers=linked,
                        checks_state=_extract_checks_state(node),
                        review_decision=str(node.get("reviewDecision") or "").upper(),
                        author_association=str(node.get("authorAssociation") or "").upper(),
                    )
                )
                raw_comments = (node.get("comments") or {}).get("nodes") or []
                for issue_num in linked:
                    bucket = self._cached_pr_comments.setdefault(issue_num, [])
                    bucket.extend(_parse_comments(raw_comments, issue_num, "pr"))
            page = conn.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            cursor = str(page["endCursor"])
        return prs

    def list_comments(self, item_numbers: set[int]) -> list[CommentEvent]:
        """Returns cached issue and linked-PR comments for the requested issue numbers."""
        result: list[CommentEvent] = []
        for num in sorted(item_numbers):
            result.extend(self._cached_issue_comments.get(num, []))
            result.extend(self._cached_pr_comments.get(num, []))
        result.sort(key=lambda c: (c.created_at, c.id))
        return result

    def get_open_items_by_numbers(self, numbers: set[int]) -> list[WorkItem]:
        """Fetches currently open tracked issues by number regardless of labels so active slots and comments never drop (H2)."""
        if not numbers:
            return []
        sorted_nums = sorted(numbers)[:50]
        data = self._graphql(build_open_issues_by_numbers_query(sorted_nums), {"owner": self._owner, "name": self._name})
        repo = data.get("repository") or {}
        found: list[WorkItem] = []
        for n in sorted_nums:
            node = repo.get(f"i{n}")
            if not isinstance(node, dict) or str(node.get("state") or "").upper() != "OPEN":
                continue
            item, node_comments = _parse_issue_node(node)
            found.append(item)
            self._cached_issue_comments[item.number] = node_comments
        return found

    def get_closed_item_numbers(self, numbers: set[int]) -> set[int]:
        """Queries GitHub in one aliased GraphQL batch to check which dependencies are closed."""
        if not numbers:
            return set()
        sorted_nums = sorted(numbers)[:50]
        data = self._graphql(build_closed_items_query(sorted_nums), {"owner": self._owner, "name": self._name})
        repo = data.get("repository") or {}
        return {
            n
            for n in sorted_nums
            if isinstance(repo.get(f"i{n}"), dict) and str(repo[f"i{n}"].get("state") or "").upper() == "CLOSED"
        }
