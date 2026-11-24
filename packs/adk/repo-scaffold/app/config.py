"""Runtime configuration loader for the starter ADK agent.

Reads environment variables lazily when called so importing this module
produces zero network or filesystem side effects.
"""
from __future__ import annotations

import dataclasses
import os


@dataclasses.dataclass(frozen=True)
class AgentSettings:
    """Holds explicit runtime settings with safe defaults for offline tests."""

    root_agent_name: str
    app_name: str
    model_name: str
    model_location: str
    otel_capture_content: str


def load_settings() -> AgentSettings:
    """Loads environment configuration lazily at runtime."""
    return AgentSettings(
        # Keep aligned with create_params.root_agent_name in agents-cli-manifest.yaml.
        root_agent_name=os.environ.get("ADK_ROOT_AGENT_NAME", "starter_adk_agent"),
        # Keep equal to the agent directory name ("app") so ADK eval and /apps/app match.
        app_name=os.environ.get("ADK_APP_NAME", "app"),
        # Use a real Vertex AI global publisher model ID (harness aliases like -high return 404).
        model_name=os.environ.get("ADK_MODEL_NAME", "gemini-4-neon"),
        model_location=os.environ.get("ADK_MODEL_LOCATION", "global"),
        otel_capture_content=os.environ.get(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
            "SPAN_AND_EVENT",
        ),
    )
