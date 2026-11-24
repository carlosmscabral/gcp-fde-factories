# Kaizen Analyst Pack Delta (`packs/gecx`)

1. Run `python3 /opt/gcp-fde/kaizen_collect.py --repo . --toolchain-manifest /opt/gcp-fde/gecx-toolchain-manifest.json --out /scion-volumes/scratchpad/kaizen-snapshot.json` before diagnosing issues.
2. Audit `verdict.json` distributions across merged PRs and flag rising `unit-test-verified`, `verifier-blocked`, or `not-verifiable-in-sandbox` rates.
3. Inspect `/scion-volumes/scratchpad/sandbox-ledger.jsonl` for leaked `[CI]` apps swept by the hourly Janitor and trace failed `finally` cleanup paths.
4. Check `hub_metrics.tool_error_rates` for repeated `cxas lint`, `cxas push`, `cxas test-callbacks`, or `BidiRunSession` failures and graduate repeated errors to deterministic tests first.
5. Check `WORKAROUNDS.yaml` entries (`WK-001` through `WK-004`) approaching the 90-day TTL and schedule their `removal_test` execution.
6. Route Step 4 research briefs exclusively via `scion msg gecx-coordinator` requesting a bounded `gecx-researcher` pass and require a full Candidate Skill Sheet.
7. Never recommend relaxing custom CES IAM roles, skipping `gecx-verdict-gate.yml`, or lowering `evals/` coverage to reduce latency or token cost.
8. Include a unified `-` / `+` diff and explicit Rollback Criterion for every prompt or harness calibration proposal.
