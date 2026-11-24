# Architect Pack Delta (`packs/adk`)

1. Design every ADK agent as a modular package (`agent.py` thin composition root <= 250 lines exporting `root_agent`, plus `config.py`, `prompts.py`, `tools/`, `guardrails/`, `telemetry.py`).
2. Explicitly select the Gemini Enterprise export mode in the design (`agent_engine` using `adkAgentDefinition` vs. `a2a` using `a2aAgentDefinition` + `AgentCard`) and document required `toolAuthorizations` when end-user OAuth applies.
3. Specify regional Agent Engine compute decoupling (`location="global"` for Gemini inference) and lazy client initialization so CloudPickle stays clean.
4. Document any surfaces unverifiable in Sandbox (interactive 3LO consent UI, private on-prem PSC MCP servers, corporate IdP group ACLs) for honest verdict labeling.
5. Require `McpToolset` `tool_list_cache_ttl_seconds` and static auth-only `header_provider` in every MCP architecture.
6. Keep prose design iterations directly between architect and human without triggering redundant code-review loops.
