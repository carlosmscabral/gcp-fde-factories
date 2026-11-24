# Kaizen Analyst Pack Delta (`packs/adk`)

1. Run `python3 /opt/gcp-fde/kaizen_collect.py --repo . --toolchain-manifest /opt/gcp-fde/adk-toolchain-manifest.json --out /scion-volumes/scratchpad/kaizen-snapshot.json` first.
2. Audit `verdict.json` trends, `adk eval` trajectory/response failures, CloudPickle regressions, and `ge_export.py` validation errors.
3. Inspect `hub_metrics.tool_error_rates` and `avgSessionDurationMs` to catch MCP cache misses, memory-preload latency regressions, or oversized `eng-manager` briefs.
4. Check `repo_drift` outputs for new Python/Node/MCP tools added to brownfield ADK repos and propose conditional `Dockerfile.customer` updates when needed.
5. Route Step 4 external skill or ADK tool discovery exclusively via `scion msg adk-coordinator` requesting a bounded `adk-researcher` pass with a Candidate Skill Sheet.
6. Never recommend relaxing `adk-code-reviewer`, shrinking `evals/`, weakening GE export validation, or skipping Sandbox verification.
7. Include a unified `-` / `+` diff and explicit Rollback Criterion for every prompt or harness calibration proposal.
