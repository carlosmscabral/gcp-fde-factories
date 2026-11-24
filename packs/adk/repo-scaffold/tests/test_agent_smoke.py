"""Offline unit tests for the starter ADK agent tools, config, and agents-cli manifest."""
from __future__ import annotations

import pathlib

from app.config import load_settings
from app.tools import health_ping

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_health_ping_returns_ok() -> None:
    """Verifies the starter tool returns a deterministic status payload."""
    assert health_ping("billing-api") == {"service": "billing-api", "status": "ok"}


def test_settings_load_defaults() -> None:
    """Verifies runtime settings align with the native agents-cli app layout."""
    cfg = load_settings()
    assert cfg.app_name == "app"
    assert cfg.root_agent_name == "starter_adk_agent"
    assert cfg.model_location == "global"
    assert cfg.otel_capture_content == "SPAN_AND_EVENT"


def test_agents_cli_manifest_matches_runtime_config() -> None:
    """Verifies agents-cli-manifest.yaml keeps agent_directory and root_agent_name aligned."""
    manifest = (REPO_ROOT / "agents-cli-manifest.yaml").read_text(encoding="utf-8")
    cfg = load_settings()
    assert 'agent_directory: "app"' in manifest
    assert 'base_template: "adk_python"' in manifest
    assert f'root_agent_name: "{cfg.root_agent_name}"' in manifest
    assert f'app_name: "{cfg.app_name}"' in manifest
    assert "is_a2a: true" in manifest
