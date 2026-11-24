# Investigator Pack Delta (`packs/adk`)

1. Report verified facts only with file paths, line numbers, stack traces, and command outputs; never make design decisions or edit production code.
2. Inspect `app/` (or legacy `agent/` in brownfield repos), `agents-cli-manifest.yaml`, `pyproject.toml`, `ge_manifest.json`, `evals/`, and `.factory/hub-project.yaml` to map existing tools, callbacks, MCP servers, and Gemini Enterprise registration settings.
3. Check for container startup and packaging blockers (root `Dockerfile` entrypoint, missing pinned deps, module-level network I/O, or `TYPE_CHECKING`-gated tool annotations) during root-cause investigations.
4. Check `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` and `McpToolset` caching settings whenever investigating trace or latency anomalies.
