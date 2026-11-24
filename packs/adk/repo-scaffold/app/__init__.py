"""Package entrypoints for the starter ADK agent using lazy SDK loading.

Exposes `app` and `root_agent` on demand so offline unit tests import
`app.config` and `app.tools` without requiring `google-adk` to be installed.
"""
from __future__ import annotations

from typing import Any

__all__ = ["app", "root_agent"]


def __getattr__(name: str) -> Any:
    """Loads ADK runtime objects lazily when first accessed."""
    if name in ("app", "root_agent"):
        from . import agent

        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
