"""Thin ADK composition root exporting root_agent (<= 250 lines).

All prompts, configuration, and tool handlers stay in dedicated submodules so CloudPickle
serializes cleanly by module reference for Vertex AI Agent Engine deployments.
"""
from __future__ import annotations

import os
from typing import Any

from .config import load_settings
from .prompts import SYSTEM_INSTRUCTION
from .tools import health_ping


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


root_agent = build_root_agent()
