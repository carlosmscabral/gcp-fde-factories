"""Thin ADK composition root exporting root_agent (<= 250 lines).

All prompts, configuration, and tool handlers stay in dedicated submodules so CloudPickle
serializes cleanly by module reference for Vertex AI Agent Engine deployments.
"""
from __future__ import annotations

from typing import Any

from .config import load_settings
from .prompts import SYSTEM_INSTRUCTION


def health_ping(service_name: str) -> dict[str, str]:
    """Returns a deterministic health payload for smoke checks and offline tool tests."""
    return {"service": service_name, "status": "ok"}


def build_root_agent() -> Any:
    """Builds the ADK LlmAgent lazily if google-adk is installed, else returns a config dict."""
    cfg = load_settings()
    try:
        from google.adk.agents import LlmAgent  # type: ignore[import-not-found]
    except ImportError:
        return {
            "name": cfg.app_name,
            "model": cfg.model_name,
            "instruction": SYSTEM_INSTRUCTION,
            "tools": [health_ping],
        }
    return LlmAgent(
        name=cfg.app_name,
        model=cfg.model_name,
        instruction=SYSTEM_INSTRUCTION,
        tools=[health_ping],
    )


root_agent = build_root_agent()
