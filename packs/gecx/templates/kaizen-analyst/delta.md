# Kaizen Analyst Pack Delta (`packs/gecx`)

1. Pass `--toolchain-manifest /opt/gcp-fde/gecx-toolchain-manifest.json` to `kaizen_collect.py` and audit `.factory/verdicts/pr-*.json` distributions (`unit-test-verified`, `verifier-blocked`, `not-verifiable-in-sandbox`).
2. Inspect `/scion-volumes/scratchpad/sandbox-ledger.jsonl` for leaked `[CI]` apps swept by the hourly Janitor and trace failed `finally` cleanup paths.
3. Check `WORKAROUNDS.yaml` entries approaching the 90-day TTL and schedule their `removal_test` execution.
4. Route Step 4 research briefs to the active coordinator agent name (default `coordinator`, resolved via `scion --format json list`) requesting `gecx-researcher`, and never relax custom CES IAM roles, `gecx-verdict-gate.yml`, or `evals/` coverage.
