# Kaizen Analyst Pack Delta (`packs/adk`)

1. Pass `--toolchain-manifest /opt/gcp-fde/adk-toolchain-manifest.json` to `kaizen_collect.py` and audit `.factory/verdicts/pr-*.json`, `adk eval` failures, CloudPickle regressions, and `ge_export.py` errors.
2. Inspect `hub_metrics.tool_error_rates` and per-agent `avgSessionDurationMs` to catch MCP latency regressions or oversized `eng-manager` briefs.
3. Check `repo_drift` outputs for new Python, Node, or MCP tools added to brownfield ADK repos and propose conditional `Dockerfile.customer` updates when needed.
4. Route Step 4 research briefs to the active coordinator agent name (default `coordinator`, resolved via `scion --format json list`) requesting `adk-researcher`, and never relax `adk-code-reviewer`, `evals/`, GE export validation, or Sandbox verification.
