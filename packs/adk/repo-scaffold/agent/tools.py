"""Deterministic starter tools kept in a dedicated submodule for modular testing and lazy I/O."""
from __future__ import annotations


def health_ping(service_name: str) -> dict[str, str]:
    """Returns a deterministic health payload for smoke checks and offline tool tests."""
    return {"service": service_name, "status": "ok"}
