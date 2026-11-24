"""Thin ADK composition root lazily exporting root_agent (<= 250 lines).

All prompts, configuration, and tool handlers stay in dedicated submodules so container
builds remain deterministic and offline unit tests run without google-adk installed.
"""
from __future__ import annotations

import os
from typing import Any

from .config import load_settings
from .prompts import SYSTEM_INSTRUCTION
from .tools import health_ping

_ROOT_AGENT: Any | None = None


def build_root_agent() -> Any:
    """Applies runtime configuration and constructs the ADK LlmAgent."""
    cfg = load_settings()
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", cfg.model_location)
    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", cfg.otel_capture_content)

    from google.adk.agents import LlmAgent  # type: ignore[import-not-found]

    return LlmAgent(
        name=cfg.app_name,
        model=cfg.model_name,
        instruction=SYSTEM_INSTRUCTION,
        tools=[health_ping],
    )


def __getattr__(name: str) -> Any:
    """Constructs root_agent on first access so module import has zero SDK or I/O side effects."""
    global _ROOT_AGENT
    if name == "root_agent":
        if _ROOT_AGENT is None:
            _ROOT_AGENT = build_root_agent()
        return _ROOT_AGENT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
