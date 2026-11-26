# Kaizen Analyst Pack Delta (`packs/generic`)

1. Pass `--toolchain-manifest /opt/gcp-fde/generic-toolchain-manifest.json` to `kaizen_collect.py` and audit PR telemetry, Level 1/2 gate failures, and Day-2 `repo_drift`.
2. Inspect `hub_metrics.tool_error_rates`, per-agent turn counts, and PR review turnaround to recommend `reviewer_replicas` or `Dockerfile.customer` improvements.
3. Run `factory_onboard.py kp-check --repo .` during weekly audits and surface broken Knowledge Plane links or stale `modernization-backlog.yaml` gaps.
4. Route Option A research briefs to the active coordinator agent name (resolved via `scion --format json list`) requesting `sw-researcher`, and never relax `sw-code-reviewer` or `sw-security-auditor` gates.
