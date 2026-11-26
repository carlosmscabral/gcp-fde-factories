"""Process-wide ADK session and artifact services shared across every serving surface.

Registers the custom `shared://` URI scheme so ADK HTTP routes, A2A JSON-RPC
handlers, and the Reasoning Engine adapter share one session store instance.
"""
from __future__ import annotations

import functools
import os
from typing import Any

from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.utils.service_factory import create_session_service_from_options

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"

_AGENT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _resolve_agent_engine_location() -> str:
    """Resolves a regional location for VertexAiSessionService and rejects global (HC-10 F9, HC-11 F4).

    Reads non-reserved ADK_AGENT_ENGINE_REGION first because Vertex AI Agent Engine rejects
    deploymentSpec.env keys starting with the reserved GOOGLE_CLOUD_AGENT_ENGINE prefix.
    """
    for env_key in (
        "ADK_AGENT_ENGINE_REGION",
        "AGENT_ENGINE_REGION",
        "CLOUD_RUN_REGION",
        "GOOGLE_CLOUD_REGION",
        "GOOGLE_CLOUD_LOCATION",
    ):
        val = (os.environ.get(env_key) or "").strip()
        if val and val.lower() != "global":
            return val
    return "us-central1"


@functools.cache
def get_session_service() -> Any:
    """Returns the process-wide session service for the current runtime target."""
    if uri := os.environ.get("SESSION_SERVICE_URI"):
        return create_session_service_from_options(
            base_dir=_AGENT_DIR, session_service_uri=uri
        )
    if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

        return VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=_resolve_agent_engine_location(),
            agent_engine_id=agent_engine_id,
        )
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return InMemorySessionService()


@functools.cache
def get_artifact_service() -> Any:
    """Returns GCS artifact storage when LOGS_BUCKET_NAME is set, else in-memory storage."""
    if bucket := os.environ.get("LOGS_BUCKET_NAME"):
        return GcsArtifactService(bucket_name=bucket)
    return InMemoryArtifactService()


_registry = get_service_registry()
_registry.register_session_service("shared", lambda uri, **kw: get_session_service())
_registry.register_artifact_service("shared", lambda uri, **kw: get_artifact_service())
