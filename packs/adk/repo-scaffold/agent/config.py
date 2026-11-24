"""Runtime configuration loader for the starter ADK agent."""
from __future__ import annotations

import dataclasses
import os


@dataclasses.dataclass(frozen=True)
class AgentSettings:
    """Holds explicit runtime settings with safe defaults for offline tests."""

    app_name: str
    model_name: str
    model_location: str
    otel_capture_content: str


def load_settings() -> AgentSettings:
    """Reads environment variables lazily at runtime rather than import time."""
    return AgentSettings(
        app_name=os.environ.get("ADK_APP_NAME", "starter_adk_agent"),
        # Use a real Vertex AI global publisher model ID (HC-01 F30: harness aliases like -high return 404).
        model_name=os.environ.get("ADK_MODEL_NAME", "gemini-4-neon"),
        model_location=os.environ.get("ADK_MODEL_LOCATION", "global"),
        otel_capture_content=os.environ.get(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
            "SPAN_AND_EVENT",
        ),
    )
