"""Thin ADK composition root lazily exporting root_agent and app (<= 250 lines).

All prompts, configuration, and tool handlers stay in dedicated submodules so
container builds stay deterministic and offline unit tests run without google-adk.
"""
from __future__ import annotations

import os
from typing import Any

from .config import load_settings
from .prompts import SYSTEM_INSTRUCTION
from .tools import health_ping

_ROOT_AGENT: Any | None = None
_ADK_APP: Any | None = None


def build_root_agent() -> Any:
    """Applies runtime configuration and constructs the ADK root Agent."""
    cfg = load_settings()
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", cfg.model_location)
    os.environ.setdefault(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
        cfg.otel_capture_content,
    )

    from google.adk.agents import Agent  # type: ignore[import-not-found]
    from google.adk.models import Gemini  # type: ignore[import-not-found]
    from google.genai import types  # type: ignore[import-not-found]

    return Agent(
        # Match create_params.root_agent_name in agents-cli-manifest.yaml for trace discovery.
        name=cfg.root_agent_name,
        model=Gemini(
            model=cfg.model_name,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[health_ping],
    )


def build_app(root_agent: Any | None = None) -> Any:
    """Wraps root_agent in an ADK App whose name matches the agent directory."""
    cfg = load_settings()
    resolved_agent = root_agent if root_agent is not None else build_root_agent()

    from google.adk.apps import App  # type: ignore[import-not-found]

    return App(
        root_agent=resolved_agent,
        name=cfg.app_name,
    )


def __getattr__(name: str) -> Any:
    """Constructs root_agent and app on first access to prevent import-time SDK side effects."""
    global _ROOT_AGENT, _ADK_APP
    if name == "root_agent":
        if _ROOT_AGENT is None:
            _ROOT_AGENT = build_root_agent()
        return _ROOT_AGENT
    if name == "app":
        if _ADK_APP is None:
            if _ROOT_AGENT is None:
                _ROOT_AGENT = build_root_agent()
            _ADK_APP = build_app(_ROOT_AGENT)
        return _ADK_APP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
