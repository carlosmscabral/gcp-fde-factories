# Developer Pack Delta (`packs/adk`)

1. Keep `agent/agent.py` under 250 lines as a thin composition root and place prompts, config, guardrails, and tools in focused submodules with lazy I/O.
2. Keep all `FunctionTool` parameter type annotations imported at module top-level (never under `TYPE_CHECKING`) when using `from __future__ import annotations`.
3. Configure `McpToolset` with `tool_list_cache_ttl_seconds=3600` and static auth-only `header_provider`; set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="SPAN_AND_EVENT"`.
4. Keep `ge_manifest.json` updated whenever display name, description, A2A skills, or Agent Engine targets change, and validate it offline with `ge_export.py validate`.
5. Run Level 1 checks (`pytest tests/ -q`, CloudPickle round-trip check, and `ge_export.py export`) before opening or updating any pull request.
6. Never modify `evals/` golden expectations in the same PR as agent code without explicit human authorization (`eval-change-approved` label).
