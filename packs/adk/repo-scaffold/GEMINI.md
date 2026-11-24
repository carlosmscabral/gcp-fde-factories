# Repository Agent Instructions (`packs/adk` Scaffold)

NOTE: Keep `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` byte-identical. CI blocks merges on divergence.

- **Deployment Standard:** Use the opinionated root `Dockerfile` and `agents-cli deploy` (`agent_runtime`, `cloud_run`, or `gke`) guided by the `google-agents-cli-*` skills.
- **Modular Layout:** Keep `agent/agent.py` under 250 lines. Place prompts in `agent/prompts.py`, config in `agent/config.py`, and tools in `agent/tools.py`.
- **MCP and Telemetry:** Set `tool_list_cache_ttl_seconds` on `McpToolset` and set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"`.
- **Gemini Enterprise Export:** Keep `ge_manifest.json` schema-valid (`agent_engine` or `a2a` with A2A `v0.3.0` skill `tags`). Never deploy to PROD from agent containers.
- **Verification:** Run `pytest tests/ -q` and `python3 /opt/adk-factory/ge_export.py validate --manifest ge_manifest.json` on every PR. Keep `evals/` 100% synthetic.
