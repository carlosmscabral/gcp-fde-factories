"""Offline unit tests for the starter ADK agent tools and configuration."""
from __future__ import annotations

from agent.config import load_settings
from agent.tools import health_ping


def test_health_ping_returns_ok() -> None:
    """Verifies the starter tool returns a deterministic status payload."""
    assert health_ping("billing-api") == {"service": "billing-api", "status": "ok"}


def test_settings_load_defaults() -> None:
    """Verifies runtime settings provide explicit model location and OTEL tracing mode."""
    cfg = load_settings()
    assert cfg.model_location == "global"
    assert cfg.otel_capture_content == "SPAN_AND_EVENT"
