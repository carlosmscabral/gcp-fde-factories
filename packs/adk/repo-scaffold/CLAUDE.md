# Repository Agent Instructions (`packs/adk` Scaffold — Native `google-agents-cli` Layout)

NOTE: Keep `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` byte-identical. CI blocks merges on divergence.

- **Deployment Standard (ADR-014):** Follow the native `google-agents-cli` (`adk_python`) layout (`app/`, `agents-cli-manifest.yaml`, `pyproject.toml`, root `Dockerfile` running `uvicorn app.fast_api_app:app` as non-root `USER appuser`). Omit `deployment/terraform/` because Stage 01 Landing Zone owns VPC and IAM.
- **Modular Layout:** Keep `app/agent.py` under 250 lines exporting `root_agent` and `app = App(root_agent=root_agent, name="app")`. Place prompts in `app/prompts.py`, config in `app/config.py`, and tools in `app/tools.py`.
- **A2A & Playground Surfaces:** Keep `app/fast_api_app.py` and `app/app_utils/` intact so one container serves ADK HTTP (`/apps/app/...`), dynamic A2A (`/a2a/app/.well-known/agent-card.json` using `APP_URL`), and Agent Engine Playground (`/api/reasoning_engine`). Never hand-write static `agent.json`.
- **MCP and Telemetry:** Set `tool_list_cache_ttl_seconds` on `McpToolset` and set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"`.
- **Gemini Enterprise Export:** Keep `ge_manifest.json` schema-valid (`agent_engine` or `a2a` with A2A `v0.3.0` skill `tags`). Never deploy to PROD from agent containers.
- **Verification:** Run `pytest tests/ -q` and `python3 /opt/adk-factory/ge_export.py validate --manifest ge_manifest.json` on every PR. Keep `evals/` 100% synthetic.
