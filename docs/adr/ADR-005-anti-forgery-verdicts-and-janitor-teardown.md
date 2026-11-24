# ADR-005: Anti-Forgery Verdicts and Janitor Teardown

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-07](../INVARIANTS.md#inv-07-anti-forgery-verdict-readback-and-commit-binding), [INV-08](../INVARIANTS.md#inv-08-ephemeral-ci-naming-and-janitor-teardown)

## Context

Autonomous coding agents can modify files inside a pull request branch, including test scripts and local JSON reports.
If a CI gate trusts a JSON report written by the coding agent without independent verification, a faulty agent can bypass quality checks.
Ephemeral Sandbox apps and ReasoningEngines also leak quota and cost if failed runs leave resources behind.

## Decision

1. Require every verified pull request to emit a Contract 5 Verdict artifact at `.factory/verdicts/pr-<n>.json` validated against `schemas/verdict.schema.json`.
2. Bind each Verdict to the exact `commit_sha`, `verification_level` (`live-gcp-verified`, `local-mock-verified`, or `static-only`), and immutable GCP resource identifiers (`sandbox_app_id`, `eval_run_ids`, or `reasoning_engine_id`).
3. Run an independent CI verifier (`scripts/verify-verdict.py` backed by `scripts/lib/verdict_checker.py`) under the read-only `sandbox_evaluator` SA via keyless GitHub Actions Workload Identity Federation.
4. Require the verifier to reject stale `commit_sha` values, synthetic fixture IDs, invalid levels, or failed live GCP API readbacks.
5. Tag every ephemeral Sandbox resource with the `[CI]` naming prefix and execute TTL teardown (`packs/gecx/scripts/sandbox_janitor.py` or `packs/adk/scripts/sandbox_janitor.py`) under the isolated `sandbox_janitor` SA.

## Consequences

- Coding agents cannot forge a passing live GCP evaluation verdict by editing branch files.
- Reviewers see auditable GCP resource IDs and exact pass/fail ratios on every pull request.
- Ephemeral resources expire cleanly even when a developer session or CI runner crashes mid-flight.

## Enforcement

- `schemas/verdict.schema.json`
- `scripts/verify-verdict.py`
- `scripts/lib/verdict_checker.py`
- `packs/gecx/scripts/gecx_sandbox_gate.py`
- `packs/gecx/scripts/sandbox_janitor.py`
- `packs/adk/scripts/adk_sandbox_gate.py`
- `packs/adk/scripts/sandbox_janitor.py`
- `tests/test_verdict_and_gate.py`
