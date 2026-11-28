"""Unit and contract tests for the Provider-Agnostic External Delta Watcher (Issue #2).

Covers deterministic SEP intake filtering, anti-echo comment and PR deduplication,
GCS ifGenerationMatch optimistic concurrency, Hub OIDC wakeup payloads, GitHub GraphQL
adapter pagination, Cloud Run HTTP routes, hub-project.yaml intake schema, and Terraform guards.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCHER_DIR = REPO_ROOT / "scripts/delta-watcher"
if str(WATCHER_DIR) not in sys.path:
    sys.path.insert(0, str(WATCHER_DIR))

from adapters.base import CommentEvent, PullRequestEvent, WorkItem  # noqa: E402
from adapters.github import GitHubTrackerAdapter  # noqa: E402
from hub_notifier import HubNotifier, format_wakeup_message  # noqa: E402
from intake_filter import IntakePolicy, WatcherState, evaluate_tick, parse_dependencies  # noqa: E402
from server import WatcherRuntime, create_handler  # noqa: E402
from state_store import ConcurrencyConflictError, GcsStateStore, LocalFileStateStore  # noqa: E402
from watcher import run_tick  # noqa: E402


def _load_parse_hub_project():
    """Dynamically loads deploy/03-hub-bootstrap/parse_hub_project.py."""
    spec = importlib.util.spec_from_file_location(
        "parse_hub_project_dw",
        REPO_ROOT / "deploy/03-hub-bootstrap/parse_hub_project.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["parse_hub_project_dw"] = mod
    spec.loader.exec_module(mod)
    return mod


def _item(
    number: int,
    labels: tuple[str, ...] = (),
    body: str = "",
    title: str = "",
    updated_at: str = "2026-11-28T00:00:00Z",
) -> WorkItem:
    """Builds a minimal normalized WorkItem fixture."""
    return WorkItem(
        id=f"I_{number}",
        number=number,
        title=title or f"Task #{number}",
        body=body,
        state="OPEN",
        labels=labels,
        author="po-human",
        url=f"https://github.com/org/repo/issues/{number}",
        updated_at=updated_at,
    )


class _StubAdapter:
    """In-memory TrackerAdapter stub for deterministic run_tick and HTTP handler tests."""

    def __init__(
        self,
        open_items: list[WorkItem],
        comments: list[CommentEvent] | None = None,
        open_prs: list[PullRequestEvent] | None = None,
        closed_nums: set[int] | None = None,
    ) -> None:
        self._open_items = open_items
        self._comments = comments or []
        self._open_prs = open_prs or []
        self._closed_nums = closed_nums or set()

    def list_open_items(self) -> list[WorkItem]:
        return list(self._open_items)

    def list_comments(self, item_numbers: set[int]) -> list[CommentEvent]:
        return [c for c in self._comments if c.item_number in item_numbers]

    def list_open_prs(self) -> list[PullRequestEvent]:
        return list(self._open_prs)

    def get_closed_item_numbers(self, numbers: set[int]) -> set[int]:
        return numbers & self._closed_nums


def test_unlabeled_issues_produce_zero_dispatches_and_scope_label_filters() -> None:
    """Confirms default-deny opt-in ignores unlabeled issues and honors optional scope_label."""
    items = [
        _item(1, labels=()),
        _item(2, labels=("bug",)),
        _item(3, labels=("factory:ready",)),
        _item(4, labels=("factory:ready", "factory:adk")),
    ]
    decision_no_scope = evaluate_tick(IntakePolicy(max_concurrent_issues=2), WatcherState(), items, [], [])
    assert [e.issue_number for e in decision_no_scope.events] == [3, 4]
    assert decision_no_scope.metrics["skipped_reasons"]["missing_release_label"] == 2

    decision_scoped = evaluate_tick(
        IntakePolicy(scope_label="factory:adk", max_concurrent_issues=2),
        WatcherState(),
        items,
        [],
        [],
    )
    assert [e.issue_number for e in decision_scoped.events] == [4]
    assert decision_scoped.metrics["skipped_reasons"]["missing_scope_label"] == 1


def test_hold_and_paused_block_new_dispatches_but_forward_active_human_replies_and_pr_signals() -> None:
    """Confirms factory:hold and intake.paused=True block new dispatches while forwarding active replies."""
    state = WatcherState(
        dispatched_issues={"10": {"title": "Active #10", "url": "https://example.com/10", "updated_at": "t1"}}
    )
    items = [
        _item(10, labels=("factory:ready",)),
        _item(11, labels=("factory:ready", "factory:hold")),
        _item(12, labels=("factory:ready", "wontfix")),
        _item(13, labels=("factory:ready",)),
    ]
    comments = [
        CommentEvent("C1", 10, "issue", "alice-po", "Please include retry backoff", "https://example.com/c1", "t2"),
    ]
    prs = [
        PullRequestEvent(
            number=99,
            title="Fix #10",
            state="OPEN",
            author="dev-bot",
            url="https://example.com/pr/99",
            updated_at="t2",
            linked_issue_numbers=(10,),
            checks_state="FAILURE",
            review_decision="CHANGES_REQUESTED",
        )
    ]

    decision = evaluate_tick(IntakePolicy(paused=True, max_concurrent_issues=3), state, items, comments, prs)
    kinds = [(e.kind, e.issue_number, e.pr_number) for e in decision.events]
    assert kinds == [("human_comment", 10, None), ("pr_action_needed", 10, 99)]
    assert decision.metrics["dispatched_ids"] == []
    assert decision.metrics["skipped_reasons"]["held_or_wontfix"] == 2
    assert decision.metrics["skipped_reasons"]["paused"] == 1

    # Next tick with unchanged PR signal and already-seen comment must emit zero wakes.
    decision2 = evaluate_tick(IntakePolicy(paused=True), decision.next_state, items, comments, prs)
    assert decision2.events == []
    assert decision2.metrics["skipped_reasons"]["unchanged_pr_signal"] == 1


def test_dependency_gating_deterministic_ordering_and_portfolio_capacity_cap() -> None:
    """Confirms Depends on #N gating, priority/wave ordering, max_concurrent_issues=2, and slot release."""
    assert parse_dependencies("Implements step.\nDepends on #5 and depends on #8.") == {5, 8}
    items = [
        _item(20, labels=("factory:ready", "wave-2")),
        _item(21, labels=("factory:ready", "priority:p0")),
        _item(22, labels=("factory:ready",), body="Depends on #5"),
        _item(23, labels=("factory:ready", "wave-1")),
    ]
    # Dependency #5 is not closed yet, so #22 is blocked. Capacity=2 picks #21 (p0) and #23 (wave-1).
    d1 = evaluate_tick(IntakePolicy(max_concurrent_issues=2), WatcherState(), items, [], [], closed_dependency_numbers=set())
    assert d1.metrics["dispatched_ids"] == [21, 23]
    assert d1.metrics["skipped_reasons"]["unmet_dependency"] == 1
    assert d1.metrics["skipped_reasons"]["capacity_full"] == 1

    # Once #21 closes and #5 is closed, capacity frees one slot and dispatches #20 (wave-2) before #22 (no wave).
    remaining = [i for i in items if i.number != 21]
    d2 = evaluate_tick(IntakePolicy(max_concurrent_issues=2), d1.next_state, remaining, [], [], closed_dependency_numbers={5})
    assert d2.metrics["dispatched_ids"] == [20]
    assert d2.metrics["active_dispatched"] == [20, 23]


def test_bot_and_marker_comments_never_cause_wakeup_loops() -> None:
    """Confirms bot logins, [bot] suffixes, echo markers, and pre-dispatch comments never wake coordinator."""
    state = WatcherState(dispatched_issues={"10": {"title": "Active", "url": "u", "updated_at": "t1"}})
    items = [_item(10, labels=("factory:ready",)), _item(11, labels=("factory:ready",))]
    comments = [
        CommentEvent("C_BOT1", 10, "issue", "github-actions[bot]", "CI failed", "u1", "t2"),
        CommentEvent("C_BOT2", 10, "pr", "custom-ci[bot]", "Lint note", "u2", "t2"),
        CommentEvent("C_ECHO", 10, "issue", "shared-pat-user", "Summary\n<!-- scion-factory -->", "u3", "t2"),
        CommentEvent("C_OLD_11", 11, "issue", "po-human", "Pre-existing note before ready", "u4", "t1"),
    ]
    d1 = evaluate_tick(IntakePolicy(max_concurrent_issues=2), state, items, comments, [])
    # Only #11 new_issue should fire; bots, marker comment, and pre-existing #11 comment must not fire human_comment.
    assert [(e.kind, e.issue_number) for e in d1.events] == [("new_issue", 11)]
    assert d1.metrics["skipped_reasons"]["bot_or_echo_comment"] == 3

    # Second tick with identical comments produces zero events.
    d2 = evaluate_tick(IntakePolicy(max_concurrent_issues=2), d1.next_state, items, comments, [])
    assert d2.events == []


def test_gcs_state_store_handles_404_generation_matching_and_412_conflicts() -> None:
    """Confirms GcsStateStore handles initial 404, sends ifGenerationMatch, and raises on HTTP 412."""
    objects: dict[str, tuple[str, bytes]] = {}
    recorded_urls: list[tuple[str, str]] = []

    def fake_http(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
        assert headers["Authorization"] == "Bearer fake-token"
        recorded_urls.append((method, url))
        if method == "GET" and "alt=media" not in url:
            if "cursor" not in objects:
                return 404, b"not found"
            gen, _ = objects["cursor"]
            return 200, json.dumps({"generation": gen}).encode("utf-8")
        if method == "GET" and "alt=media" in url:
            _, data = objects["cursor"]
            return 200, data
        if method == "POST":
            expected = url.split("ifGenerationMatch=")[1].split("&")[0]
            current = objects["cursor"][0] if "cursor" in objects else "0"
            if expected != current:
                return 412, b"Precondition Failed"
            next_gen = str(int(current) + 1)
            objects["cursor"] = (next_gen, body or b"{}")
            return 200, json.dumps({"generation": next_gen}).encode("utf-8")
        raise AssertionError(f"Unexpected {method} {url}")

    store = GcsStateStore(
        bucket="hub-dw-bucket",
        object_name="delta-watcher/cursor.json",
        token_provider=lambda: "fake-token",
        http_request=fake_http,
    )
    state0, gen0 = store.load()
    assert state0 == {} and gen0 == "0"

    gen1 = store.save({"dispatched_issues": {"7": {"title": "A"}}}, gen0)
    assert gen1 == "1"
    assert any("ifGenerationMatch=0" in u for m, u in recorded_urls if m == "POST")

    # Concurrent stale writer using gen0 must fail with ConcurrencyConflictError.
    with pytest.raises(ConcurrencyConflictError):
        store.save({"dispatched_issues": {"8": {"title": "B"}}}, gen0)

    loaded, gen_loaded = store.load()
    assert gen_loaded == "1"
    assert loaded["dispatched_issues"]["7"]["title"] == "A"


def test_run_tick_rolls_back_cursor_when_hub_is_off_hours(tmp_path: pathlib.Path) -> None:
    """Confirms off-hours Hub outages roll back claimed cursor state so the next tick retries cleanly."""
    store = LocalFileStateStore(tmp_path / "cursor.json")
    adapter = _StubAdapter(open_items=[_item(42, labels=("factory:ready",))])
    failing_notifier = HubNotifier(
        hub_url="http://10.42.0.5:8080",
        project_id="proj-uuid-1",
        token_provider=lambda aud: f"oidc:{aud}",
        http_post=lambda url, payload, headers, timeout: (503, b"hub asleep"),
    )
    with pytest.raises(RuntimeError, match="Hub wake failed"):
        run_tick(adapter, store, IntakePolicy(), "org/repo", notifier=failing_notifier)

    # Cursor must not have issue #42 committed after failed wake.
    persisted, _ = store.load()
    assert persisted.get("dispatched_issues", {}) == {}

    # When Hub returns HTTP 200 on the next tick, issue #42 wakes coordinator once and persists.
    sent: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def ok_post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        sent.append((url, payload, headers))
        return 200, b'{"ok": true}'

    ok_notifier = HubNotifier(
        hub_url="http://10.42.0.5:8080",
        project_id="proj-uuid-1",
        coordinator_agent="adk-coordinator",
        token_provider=lambda aud: f"oidc:{aud}",
        http_post=ok_post,
    )
    res = run_tick(adapter, store, IntakePolicy(), "org/repo", notifier=ok_notifier)
    assert res["dispatched_ids"] == [42]
    assert res["hub_wake_status"] == "woken"
    assert sent[0][0] == "http://10.42.0.5:8080/api/v1/projects/proj-uuid-1/agents/adk-coordinator/message"
    assert sent[0][1]["wake"] is True
    assert sent[0][2]["Authorization"].startswith("Bearer oidc:")


def test_github_adapter_parses_graphql_issues_prs_comments_and_closed_deps() -> None:
    """Confirms GitHubTrackerAdapter parses paginated GraphQL responses without live network calls."""
    calls: list[str] = []

    def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        q = payload["query"]
        calls.append(q)
        if "issues(states: OPEN" in q:
            return {
                "data": {
                    "repository": {
                        "issues": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "I_1",
                                    "number": 7,
                                    "title": "Add healthz",
                                    "body": "Depends on #3",
                                    "state": "OPEN",
                                    "url": "https://github.com/o/r/issues/7",
                                    "updatedAt": "2026-11-28T00:00:00Z",
                                    "author": {"login": "human-po"},
                                    "labels": {"nodes": [{"name": "factory:ready"}]},
                                    "comments": {
                                        "nodes": [
                                            {
                                                "id": "IC_1",
                                                "body": "Go ahead",
                                                "url": "https://github.com/o/r/issues/7#c1",
                                                "createdAt": "2026-11-28T00:05:00Z",
                                                "author": {"login": "human-po"},
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        if "pullRequests(states: OPEN" in q:
            return {
                "data": {
                    "repository": {
                        "pullRequests": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "number": 15,
                                    "title": "Implement #7",
                                    "body": "Closes #7",
                                    "state": "OPEN",
                                    "url": "https://github.com/o/r/pull/15",
                                    "updatedAt": "2026-11-28T00:10:00Z",
                                    "reviewDecision": "CHANGES_REQUESTED",
                                    "author": {"login": "dev-agent"},
                                    "closingIssuesReferences": {"nodes": [{"number": 7}]},
                                    "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
                                    "comments": {"nodes": []},
                                }
                            ],
                        }
                    }
                }
            }
        return {"data": {"repository": {"i3": {"number": 3, "state": "CLOSED"}}}}

    adapter = GitHubTrackerAdapter("o/r", token="ghp_test", http_post=fake_post)
    items = adapter.list_open_items()
    prs = adapter.list_open_prs()
    comments = adapter.list_comments({7})
    closed = adapter.get_closed_item_numbers({3})

    assert len(items) == 1 and items[0].number == 7 and items[0].labels == ("factory:ready",)
    assert len(prs) == 1 and prs[0].linked_issue_numbers == (7,) and prs[0].checks_state == "FAILURE"
    assert len(comments) == 1 and comments[0].id == "IC_1"
    assert closed == {3}
    assert "External Delta Watcher" in format_wakeup_message("o/r", "github", [])


def test_cloud_run_http_server_healthz_and_tick_routes(tmp_path: pathlib.Path) -> None:
    """Confirms server.py serves GET /healthz and POST /tick cleanly over local HTTP."""
    runtime = WatcherRuntime(
        repo_slug="org/repo",
        policy=IntakePolicy(max_concurrent_issues=2),
        adapter=_StubAdapter(open_items=[_item(5, labels=("factory:ready",))]),
        state_store=LocalFileStateStore(tmp_path / "cursor.json"),
        notifier=None,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(runtime))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
            health = json.loads(resp.read().decode("utf-8"))
            assert health["status"] == "ok" and health["repo"] == "org/repo"

        req = urllib.request.Request(f"http://127.0.0.1:{port}/tick", data=b"{}", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            tick1 = json.loads(resp.read().decode("utf-8"))
            assert tick1["dispatched_ids"] == [5] and tick1["hub_wake_status"] == "dry_run"

        req2 = urllib.request.Request(f"http://127.0.0.1:{port}/tick", data=b"{}", method="POST")
        with urllib.request.urlopen(req2, timeout=5) as resp:
            tick2 = json.loads(resp.read().decode("utf-8"))
            assert tick2["dispatched_ids"] == [] and tick2["hub_wake_status"] == "skipped"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hub_project_intake_schema_and_parser_backward_compat(tmp_path: pathlib.Path) -> None:
    """Confirms hub-project.schema.json and parse_hub_project.py accept optional intake and enforce bounds."""
    mod = _load_parse_hub_project()
    repo = tmp_path / "repo"
    (repo / ".factory").mkdir(parents=True)
    base_cfg = {
        "schema_version": "1",
        "pack": "adk",
        "pack_version": "0.5.0",
        "mode": "sandbox-direct",
        "diversity_profile": "cross-model",
        "limits": {"default_max_duration": "2h", "default_max_turns": 60, "auto_suspend_idle": True},
        "overlay_skills": [],
    }
    # 1. Backward compatible when intake is omitted.
    (repo / ".factory/hub-project.yaml").write_text(yaml.safe_dump(base_cfg), encoding="utf-8")
    parsed_default = mod.parse_hub_project(repo, expected_pack="adk")
    assert parsed_default["intake"]["enabled"] is False
    assert parsed_default["intake"]["max_concurrent_issues"] == 2
    assert parsed_default["intake"]["release_label"] == "factory:ready"

    # 2. Accepts full declarative intake block.
    with_intake = {
        **base_cfg,
        "intake": {
            "enabled": True,
            "provider": "github",
            "max_concurrent_issues": 3,
            "scope_label": "factory:adk",
            "release_label": "factory:ready",
            "hold_label": "factory:hold",
            "cadence_cron": "*/5 * * * *",
            "time_zone": "America/Sao_Paulo",
            "paused": False,
        },
    }
    (repo / ".factory/hub-project.yaml").write_text(yaml.safe_dump(with_intake), encoding="utf-8")
    parsed = mod.parse_hub_project(repo, expected_pack="adk")
    assert parsed["intake"]["enabled"] is True and parsed["intake"]["max_concurrent_issues"] == 3

    # 3. Rejects max_concurrent_issues above SEP ceiling (3).
    bad_intake = {**base_cfg, "intake": {"enabled": True, "max_concurrent_issues": 5}}
    (repo / ".factory/hub-project.yaml").write_text(yaml.safe_dump(bad_intake), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.parse_hub_project(repo, expected_pack="adk")


def test_delta_watcher_module_budgets_terraform_isolation_and_coordinator_deltas() -> None:
    """Confirms <= 250 lines/module, least-privilege Stage 01/02 TF, and coordinator SEP deltas."""
    expected_modules = [
        WATCHER_DIR / "adapters/base.py",
        WATCHER_DIR / "adapters/github.py",
        WATCHER_DIR / "adapters/github_queries.py",
        WATCHER_DIR / "intake_models.py",
        WATCHER_DIR / "intake_filter.py",
        WATCHER_DIR / "state_store.py",
        WATCHER_DIR / "hub_notifier.py",
        WATCHER_DIR / "watcher.py",
        WATCHER_DIR / "server.py",
    ]
    for path in expected_modules:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 250, f"{path.name} has {lines} lines (limit: 250)"

    s1_dw = (REPO_ROOT / "deploy/01-landing-zone/delta_watcher.tf").read_text(encoding="utf-8")
    assert 'roles/storage.objectUser' in s1_dw
    assert 'objects/delta-watcher/' in s1_dw
    assert 'roles/secretmanager.secretAccessor' in s1_dw
    assert 'roles/logging.logWriter' in s1_dw
    assert 'aiplatform' not in s1_dw
    assert 'sandbox_project_id' not in s1_dw

    s2_dw = (REPO_ROOT / "deploy/02-factory-runtime/lite-vm/delta_watcher.tf").read_text(encoding="utf-8")
    assert 'INGRESS_TRAFFIC_INTERNAL_ONLY' in s2_dw
    assert 'PRIVATE_RANGES_ONLY' in s2_dw
    assert 'roles/run.invoker' in s2_dw
    assert 'oidc_token' in s2_dw

    for pack in ("adk", "gecx", "generic"):
        delta = (REPO_ROOT / f"packs/{pack}/templates/coordinator/delta.md").read_text(encoding="utf-8")
        assert "[External Delta Watcher]" in delta
        assert "<!-- scion-factory -->" in delta
