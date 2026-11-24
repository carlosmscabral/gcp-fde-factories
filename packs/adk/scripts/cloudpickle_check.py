#!/usr/bin/env python3
"""Isolated CloudPickle serialization round-trip checker for ADK root_agent modules.

Verifies that agent/agent.py exports a serializable root_agent without live module-level
sockets, database handles, or non-picklable closures before Vertex AI Agent Engine deploys.
"""
from __future__ import annotations

import argparse
import importlib
import pathlib
import sys


def main(argv: list[str] | None = None) -> int:
    """Imports target module:attr and round-trips it through cloudpickle.dumps/loads."""
    parser = argparse.ArgumentParser(description="Verify CloudPickle round-trip for an ADK root_agent.")
    parser.add_argument("--repo-dir", required=True, type=pathlib.Path)
    parser.add_argument("--module", default="agent.agent")
    parser.add_argument("--attr", default="root_agent")
    args = parser.parse_args(argv)

    repo = args.repo_dir.resolve()
    sys.path.insert(0, str(repo))
    try:
        import cloudpickle  # type: ignore[import-not-found]
    except ImportError as exc:
        print(f"CLOUDPICKLE CHECK SKIPPED/ERROR: cloudpickle not installed: {exc}", file=sys.stderr)
        return 2

    try:
        mod = importlib.import_module(args.module)
        obj = getattr(mod, args.attr)
        blob = cloudpickle.dumps(obj)
        restored = cloudpickle.loads(blob)
    except Exception as exc:
        print(f"CLOUDPICKLE CHECK FAILED ({args.module}:{args.attr}): {exc}", file=sys.stderr)
        return 1

    print(f"CLOUDPICKLE OK ({args.module}:{args.attr}, {len(blob)} bytes, type={type(restored).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
