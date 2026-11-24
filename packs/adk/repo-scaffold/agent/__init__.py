"""Package entrypoint lazily exporting root_agent for ADK CLI and offline tests."""
from __future__ import annotations

from typing import Any

from . import agent

__all__ = ["agent", "root_agent"]


def __getattr__(name: str) -> Any:
    """Resolves root_agent lazily so offline unit tests run without google-adk installed."""
    if name == "root_agent":
        return agent.root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
