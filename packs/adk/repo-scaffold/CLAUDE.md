# Repository Agent Instructions (`packs/adk`)

## Architecture and Verification

1. Keep `agent/agent.py` as a thin composition root (`<= 250` lines) exporting `root_agent`. Place prompts, config, guardrails, and tools in submodules under `agent/`.
2. Read `.factory/hub-project.yaml`, `ge_manifest.json`, and `knowledge-plane/INDEX.md` before planning or implementing changes.
3. Run Level 1 offline verification (`pytest tests/ -q` and `python3 /opt/adk-factory/ge_export.py validate --manifest ge_manifest.json`) before opening a pull request.
4. Keep `McpToolset` `tool_list_cache_ttl_seconds` explicit and set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"`.
5. Never deploy directly to DEV, HML, or PRD or register agents in production Gemini Enterprise Apps from factory agents.
6. Never modify `evals/` golden expectations in the same PR as `agent/` code without human `eval-change-approved` authorization.
