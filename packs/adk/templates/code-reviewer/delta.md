# Code Reviewer Pack Delta (`packs/adk`)

1. Follow `google-agents-cli-adk-code` when auditing ADK 2.15+ patterns, tools, callbacks, and state management.
2. Block any PR that places prompts, config, or tool implementations monolithically inside `agent/agent.py` over 250 lines.
3. Block any PR that breaks the root `Dockerfile` contract or removes pinned versions from `requirements.txt`.
4. Block any PR that configures `McpToolset` without `tool_list_cache_ttl_seconds` or introduces un-gated per-step memory calls.
5. Verify `ge_manifest.json` omits undefined `toolSettings`, includes `tags` on A2A skills, and uses `agent_authorization` for A2A OAuth.
6. Verify `evals/` contains synthetic data only and requires human label `eval-change-approved` when modified.
