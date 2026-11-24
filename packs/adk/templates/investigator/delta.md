# Investigator Pack Delta (`packs/adk`)

1. Report verified facts only with file paths, line numbers, stack traces, and command outputs; never make design decisions or edit production code.
2. Inspect `agent/`, `ge_manifest.json`, `evals/`, and `.factory/hub-project.yaml` to map existing tools, callbacks, MCP servers, and Gemini Enterprise registration settings.
3. Check for CloudPickle serialization blockers (module-level gRPC clients, locks, or `TYPE_CHECKING`-gated tool annotations) during root-cause investigations.
4. Check `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` and `McpToolset` caching settings whenever investigating trace or latency anomalies.
