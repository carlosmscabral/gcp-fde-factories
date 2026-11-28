#!/usr/bin/env python3
"""External Delta Watcher tick orchestrator and legacy offline CLI helper.

Preserves backward-compatible compute_deltas, load_cursor, and save_cursor functions while
orchestrating provider-agnostic polling, deterministic SEP filtering, Hub wake, and
optimistic-concurrency cursor updates.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from typing import Any

# Ensure sibling modules resolve when executed as a standalone script or loaded via importlib.
_THIS_DIR = str(pathlib.Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from adapters.base import TrackerAdapter  # noqa: E402
from hub_notifier import HubNotifier  # noqa: E402
from intake_filter import IntakePolicy, WatcherState, evaluate_tick, parse_dependencies  # noqa: E402
from state_store import ConcurrencyConflictError, StateStore  # noqa: E402


def compute_deltas(
    previous_state: dict[str, str], current_items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Returns items whose updated_at changed since previous_state plus the new state map."""
    deltas: list[dict[str, Any]] = []
    next_state = dict(previous_state)
    for item in current_items:
        key = f"{item.get('kind', 'item')}#{item['number']}"
        updated = str(item.get("updated_at", ""))
        if previous_state.get(key) != updated:
            deltas.append(item)
            next_state[key] = updated
    return deltas, next_state


def load_cursor(cursor_path: pathlib.Path) -> dict[str, str]:
    """Loads persisted watcher state or returns an empty mapping on first run."""
    if not cursor_path.exists():
        return {}
    return json.loads(cursor_path.read_text(encoding="utf-8"))


def save_cursor(cursor_path: pathlib.Path, state: dict[str, str]) -> None:
    """Persists updated watcher state atomically via temp file and os.replace."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cursor-", dir=str(cursor_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        os.replace(tmp_name, cursor_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def run_tick(
    adapter: TrackerAdapter,
    state_store: StateStore,
    policy: IntakePolicy,
    repo_slug: str,
    notifier: HubNotifier | None = None,
    max_conflict_retries: int = 2,
) -> dict[str, Any]:
    """Executes one idempotent poll-filter-persist-wake cycle with optimistic locking.

    Commits the claimed cursor via ifGenerationMatch before waking the Hub so concurrent
    Cloud Scheduler ticks never double-dispatch. If the Hub wake fails (for example during
    scheduled VM off-hours), restores the prior cursor so the next tick retries cleanly.
    """
    last_conflict: ConcurrencyConflictError | None = None
    for _ in range(max(1, max_conflict_retries + 1)):
        raw_state, generation = state_store.load()
        prev_state = WatcherState.from_dict(raw_state)

        open_items = adapter.list_open_items()
        open_nums = {item.number for item in open_items}
        active_prev_nums = {int(k) for k in prev_state.dispatched_issues if k.isdigit()}
        missing_active = active_prev_nums - open_nums
        # Preserve still-open dispatched issues even if their release label was removed (H2).
        if missing_active and hasattr(adapter, "get_open_items_by_numbers"):
            extra_open = adapter.get_open_items_by_numbers(missing_active)
            open_items.extend(extra_open)
            open_nums.update(item.number for item in extra_open)

        open_prs = adapter.list_open_prs()

        referenced_deps: set[int] = set()
        for item in open_items:
            referenced_deps.update(parse_dependencies(item.body))
        closed_deps = adapter.get_closed_item_numbers(referenced_deps - open_nums)

        comments = adapter.list_comments(active_prev_nums | open_nums)

        decision = evaluate_tick(
            policy=policy,
            state=prev_state,
            open_items=open_items,
            comments=comments,
            open_prs=open_prs,
            closed_dependency_numbers=closed_deps,
        )

        next_dict = decision.next_state.to_dict()
        state_changed = next_dict != prev_state.to_dict()
        new_generation = generation

        if state_changed:
            try:
                new_generation = state_store.save(next_dict, generation)
            except ConcurrencyConflictError as exc:
                last_conflict = exc
                continue

        wake_result: dict[str, Any] = {"status": "skipped", "reason": "no_events"}
        if decision.events and notifier is not None:
            try:
                wake_result = notifier.wake_coordinator(repo_slug, policy.provider, decision.events)
            except Exception as exc:
                # Roll back cursor when Hub is unreachable so off-hours ticks retry cleanly.
                if state_changed:
                    try:
                        state_store.save(prev_state.to_dict(), new_generation)
                    except ConcurrencyConflictError:
                        pass
                raise RuntimeError(f"Hub wake failed and cursor rollback attempted: {exc}") from exc
        elif decision.events and notifier is None:
            wake_result = {"status": "dry_run", "event_count": len(decision.events)}

        return {
            **decision.metrics,
            "event_count": len(decision.events),
            "hub_wake_status": wake_result["status"],
            "wake_detail": wake_result,
        }

    raise ConcurrencyConflictError(f"Exhausted state conflict retries: {last_conflict}")


def main(argv: list[str] | None = None) -> int:
    """Runs the legacy offline JSON cursor diff CLI for backward compatibility."""
    parser = argparse.ArgumentParser(description="Compute repository Issue/PR deltas against a persisted cursor.")
    parser.add_argument("--cursor", required=True, type=pathlib.Path)
    parser.add_argument("--items-json", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    prev = load_cursor(args.cursor)
    items = json.loads(args.items_json.read_text(encoding="utf-8"))
    deltas, next_state = compute_deltas(prev, items if isinstance(items, list) else [])
    save_cursor(args.cursor, next_state)
    print(json.dumps({"delta_count": len(deltas), "deltas": deltas}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
