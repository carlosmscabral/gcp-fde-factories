"""Unified FastAPI serving entrypoint following the native google-agents-cli layout.

Exposes three serving surfaces from one container image:
- ADK HTTP API (`/apps/app/...`, `/run_sse`)
- Dynamic A2A (`/a2a/app/.well-known/agent-card.json` and `/a2a/app` JSON-RPC)
- Reasoning Engine Playground adapter (`/api/reasoning_engine`, `/api/stream_reasoning_engine`)
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator

from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.reasoning_engine_adapter import attach_reasoning_engine_routes

load_dotenv()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
otel_to_cloud = os.environ.get(
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY",
    os.environ.get("OTEL_TO_CLOUD", ""),
).lower() in ("true", "1")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    """Builds the shared ADK Runner and attaches dynamic A2A routes at startup."""
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    fastapi_app.state.runner = runner
    fastapi_app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        fastapi_app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "starter-adk-agent"
app.description = "API for interacting with the starter ADK agent"

# Register Reasoning Engine proxy routes for Agent Runtime Playground and Gemini Enterprise.
attach_reasoning_engine_routes(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
