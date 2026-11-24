"""Deterministic starter tools kept separate from agent/agent.py for clean CloudPickle serialization."""
from __future__ import annotations


def health_ping(service_name: str) -> dict[str, str]:
    """Returns a deterministic health payload for smoke checks and offline tool tests."""
    return {"service": service_name, "status": "ok"}
