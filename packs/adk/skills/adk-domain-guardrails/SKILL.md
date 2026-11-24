---
name: adk-domain-guardrails
description: Production ADK modular architecture, CloudPickle packaging hygiene, MCP/Memory latency rules, OTel capture settings, and adk eval verification gates.
---

# ADK Domain Guardrails (`packs/adk`)

## 1. Modular ADK Package and CloudPickle Hygiene
- Keep `agent/agent.py` strictly as a thin composition root (`<= 250` lines) that exports `root_agent` and keep `agent/__init__.py` exporting `from . import agent`.
- Separate configuration (`config.py`), prompts (`prompts.py`), tools (`tools/`), guardrails (`guardrails/`), and observability (`telemetry.py`) into focused modules with acyclic imports and lazy SDK client creation.
- When using `from __future__ import annotations` inside `tools/*.py`, keep all tool parameter type annotations imported at module top-level (never gated behind `TYPE_CHECKING`) so runtime schema introspection succeeds.
- Before deploying `AdkApp` to Vertex AI Agent Engine, verify CloudPickle serialization in an isolated subprocess containing only the packaged `agent/` directory so unserializable clients fail fast offline.
- source: https://google.github.io/adk-docs/deploy/agent-engine/

## 2. MCP Toolset and Memory Latency Hygiene
- Configure `McpToolset` with an explicit `tool_list_cache_ttl_seconds` (for example `3600`) and return only static or cached auth headers from `header_provider` (never per-span `traceparent` headers that bust the tool-list cache on every turn).
- Gate memory retrieval by `tool_context.invocation_id` when wrapping memory preload tools so memory search runs at most once per user turn instead of repeating before every inner tool-calling loop.
- Decouple regional Agent Engine compute from model inference location (`location="global"` for supported Gemini models) to avoid regional quota contention.
- source: https://google.github.io/adk-docs/tools/mcp-tools/

## 3. OpenTelemetry Capture and Evaluation Pyramid
- When enabling GenAI experimental OpenTelemetry semantic conventions (`OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental"`), set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"` (never `"true"`, which falls back to `NO_CONTENT`).
- Run Level 1 checks offline with zero Google Cloud credentials: `pytest` with fake tool backends, CloudPickle round-trip check, PII scan over `evals/`, and GE manifest validation.
- Run Level 2 live evaluations under the dedicated `adk-eval-tester` Service Account using `adk eval --config_file_path` (measuring `tool_trajectory_avg_score` and `final_response_match_v2`) against the ephemeral `[CI]` Agent Engine resource.
- source: https://google.github.io/adk-docs/evaluate/
