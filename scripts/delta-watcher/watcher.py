#!/usr/bin/env python3
"""Out-of-LLM GitHub Delta Watcher comparing repository event state before waking coordinator.

Maintains a small JSON cursor of last-seen updated_at timestamps per Issue and PR.
Emits wakeup payloads only when a genuine delta occurs so idle coordinator turns stay at zero.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any


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
    """Persists updated watcher state atomically."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
