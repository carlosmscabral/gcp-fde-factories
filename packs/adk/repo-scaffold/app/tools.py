"""Deterministic starter tools isolated from the composition root.

Keep every FunctionTool parameter type imported at module top level so ADK
schema inspection via typing.get_type_hints succeeds under postponed annotations.
"""
from __future__ import annotations


# Deterministic stub tool used by offline pytest checks and synthetic eval suites.
def health_ping(service_name: str) -> dict[str, str]:
    """Return the health status for a named internal service.

    Args:
        service_name: The identifier of the service to check.

    Returns:
        A dictionary containing the service name and its status.
    """
    return {"service": service_name, "status": "ok"}
