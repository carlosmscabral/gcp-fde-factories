# Developer Pack Delta (`packs/adk`)

1. Follow `google-agents-cli-adk-code` and `google-agents-cli-scaffold` for modular ADK 2.15+ packages and container-based layout.
2. Keep `agent/agent.py` under 250 lines as a thin composition root. Place prompts, config, and tools in dedicated submodules.
3. Maintain the root `Dockerfile` and pinned `requirements.txt` as the opinionated container deployment contract.
4. Set `tool_list_cache_ttl_seconds` on `McpToolset` and pass static headers with `header_provider`.
5. Update `ge_manifest.json` whenever agent capabilities, A2A skills (`tags` mandatory), or OAuth authorizations change.
6. Run `pytest tests/ -q` and `python3 /opt/adk-factory/ge_export.py validate --manifest ge_manifest.json` before requesting review.
