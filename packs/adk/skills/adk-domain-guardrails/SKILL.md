---
name: adk-domain-guardrails
description: Opinionated Dockerfile-first ADK 2.15+ deployment using upstream google/agents-cli skills, modular agent packages, MCP caching, and adk eval.
---

# ADK Domain Guardrails (`packs/adk`)

## 1. Opinionated Dockerfile-First Deployment (`agents-cli`)
- Default every ADK project to container-based deployment via a root `Dockerfile` and `agents-cli deploy` (`agent_runtime`, `cloud_run`, or `gke`).
- Follow the mounted upstream `google-agents-cli-*` skills (`workflow`, `scaffold`, `adk-code`, `eval`, `deploy`, `publish`, `observability`) as the primary reference.
- Keep `agent/agent.py` as a thin composition root (`<= 250` lines) exporting `root_agent`, with prompts, config, and tools in separate submodules.
- Validate the root `Dockerfile` contract (non-root user, explicit `adk api_server` entrypoint, pinned dependencies) before any Sandbox deploy.
- source: https://github.com/google/agents-cli

## 2. MCP Toolsets, Memory Gating, and Model Location
- On `google-adk 2.15.0`, set `tool_list_cache_ttl_seconds` on `McpToolset` and pass static headers with `header_provider`.
- Gate `PreloadMemoryTool` or `VertexAiMemoryBankService` queries by `invocation_id` to prevent per-step memory storms.
- Decouple Vertex AI inference location (`GOOGLE_CLOUD_LOCATION=global`) from Agent Runtime hosting region (`us-central1`).
- Enable `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"` for container telemetry.
- source: https://google.github.io/adk-docs/tools/mcp-tools/

## 3. Two-Tier ADK Verification and Split-SA Discipline
- Level 1 runs offline with scrubbed credentials (`pytest`, `Dockerfile` check, `ge_export.py validate`).
- Level 2 separates Deployer (`adk-deployer` SA) and Evaluator (`adk-evaluator` SA).
- Run `adk eval agent evals/synthetic/<name>.evalset.json --config_file_path evals/eval_config.json --print_detailed_results` and fail closed when `Tests passed == 0` or `Tests failed > 0`.
- source: https://google.github.io/adk-docs/evaluate/
