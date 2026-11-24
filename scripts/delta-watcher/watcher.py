#!/usr/bin/env python3
"""Out-of-LLM GitHub Delta Watcher comparing repository event state before waking coordinator.

Maintains an atomically persisted JSON cursor of last-seen updated_at timestamps per Issue
and PR. Emits wakeup payloads only when a genuine delta occurs so idle coordinator turns stay zero.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import tempfile
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


def main(argv: list[str] | None = None) -> int:
    """Reads an event items JSON file, prints only genuine deltas, and updates cursor atomically."""
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
