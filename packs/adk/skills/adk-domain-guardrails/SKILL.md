---
name: adk-domain-guardrails
description: Native google-agents-cli (adk_python) Dockerfile-first ADK 2.15+ layout, modular app packages, dynamic A2A, MCP caching, and fail-closed eval.
---

# ADK Domain Guardrails (`packs/adk`)

## 1. Native `google-agents-cli` (`adk_python`) Container Contract (ADR-014)
- Standardize every greenfield ADK project on the native `google-agents-cli` (`adk_python`) layout (`app/`, `agents-cli-manifest.yaml`, `pyproject.toml`, root `Dockerfile` running `uvicorn app.fast_api_app:app` under non-root `USER appuser`).
- Follow the mounted upstream `google-agents-cli-*` skills (`workflow`, `scaffold`, `adk-code`, `eval`, `deploy`, `publish`, `observability`) as the primary reference.
- Keep `app/agent.py` as a thin composition root (`<= 250` lines) lazily exporting `root_agent` and `app = App(root_agent=root_agent, name="app")`, with prompts in `app/prompts.py`, config in `app/config.py`, and tools in `app/tools.py`.
- Keep `agents-cli-manifest.yaml` aligned with `app/config.py` (`agent_directory: "app"`, `app_name: "app"`, matching `root_agent_name`) so `/apps/app`, `/a2a/app`, and `adk eval app` resolve consistently.
- Preserve `app/fast_api_app.py` and `app/app_utils/{a2a.py,services.py,reasoning_engine_adapter.py}` so one container serves ADK HTTP, dynamic A2A (`/a2a/app/.well-known/agent-card.json` with v0.3 JSON-RPC compat), and Agent Engine Playground (`/api/reasoning_engine`) without static `agent.json`.
- Omit `deployment/terraform/` from agent repositories because Stage 01 Landing Zone (`deploy/01-landing-zone/`) owns VPC, zero-PII Custom Roles, split SAs, and FinOps budgets.
- When deploying ephemeral Cloud Run A2A services for Contract 5 CI verification, label the service with `pr=pr-<N>` and `commit=<sha7>`, attach the same-project `<prefix>-adk-runtime@<sandbox_project_id>` SA (HC-02 F10, HC-03 F5), and pass `APP_URL=<https-service-url>` so the dynamic `AgentCard` advertises the real HTTPS endpoint.
- Validate the root `Dockerfile` contract (non-root literal `USER`, `uvicorn app.fast_api_app:app`, pinned `pyproject.toml` deps via `uv`) before any Sandbox deploy.
- source: https://github.com/google/agents-cli

## 2. MCP Toolsets, Memory Gating, and Model Location
- On `google-adk 2.15.0`, set `tool_list_cache_ttl_seconds` on `McpToolset` and pass static headers with `header_provider`.
- Gate `PreloadMemoryTool` or `VertexAiMemoryBankService` queries by `invocation_id` to prevent per-step memory storms.
- Keep deployed Agent Engine container `GOOGLE_CLOUD_LOCATION` regional (such as `us-central1`) so `VertexAiSessionService` resolves sessions cleanly via `app/app_utils/services.py`, and route only Gemini model calls to `global` via client options (HC-02 F14).
- Never pass reserved GCP project env vars (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_QUOTA_PROJECT`) in Vertex AI Agent Engine `deploymentSpec.env` (returns HTTP `400 FAILED_PRECONDITION`). Prefer `agents-cli deploy` and use non-reserved app env vars for cross-project inference.
- Enable `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"` for container telemetry.
- source: https://google.github.io/adk-docs/tools/mcp-tools/

## 3. Two-Tier ADK Verification and Split-SA Discipline
- Level 1 runs offline with scrubbed credentials (`pytest`, `Dockerfile` check, `ge_export.py validate`).
- Level 2 separates Deployer (`adk-deployer` SA) and Evaluator (`adk-evaluator` SA).
- Run `adk eval app evals/synthetic/<name>.evalset.json --config_file_path evals/eval_config.json --print_detailed_results` (or `agents-cli eval run` with explicit thresholds/JSON check) and fail closed when `Tests passed == 0` or `Tests failed > 0`.
- For brownfield ADK repositories adopted via `factory-onboard` using a legacy `agent/` directory, pass `--agent-dir agent` or rely on `adk_sandbox_gate.py` auto-detection without forcing a rewrite.
- source: https://google.github.io/adk-docs/evaluate/
