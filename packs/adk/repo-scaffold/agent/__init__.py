"""Package entrypoint exporting root_agent for ADK CLI and Vertex AI Agent Engine."""
from . import agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
