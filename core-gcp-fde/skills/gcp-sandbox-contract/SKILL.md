---
name: gcp-sandbox-contract
description: Defines the 6-level Verdict ladder, synthetic data requirements, PR Sandbox locking, and Janitor lifecycle rules across GECX and ADK packs.
---

# GCP Sandbox Verification Contract

## 1. Six-Level Verdict Ladder
Record one exact value in the Verdict JSON (`schemas/verdict.schema.json`):
1. `live-gcp-verified`: Level 1 offline checks plus live Sandbox verification read back via API in CI.
2. `not-verifiable-in-sandbox`: change affects surfaces without a Sandbox simulator (SIP trunk, SBC, AudioCodes VAIC, DTMF, CCaaS transfer). List every unverified surface for human sign-off.
3. `unit-test-verified`: only Level 1 offline tests executed. List every skipped live gate.
4. `static-check-only`: only static lint or schema validation executed.
5. `verifier-blocked`: missing credentials, quota, or Sandbox availability. Never treat as passing.
6. `verifier-failed`: functional failure, regression, PII match, or security boundary failure.
- source: https://github.com/GoogleCloudPlatform/cxas-scrapi

## 2. Anti-Forgery Provenance Rules
- Include `pack` (`gecx` or `adk`), `pr_number`, `commit_sha`, `diversity_profile`, `ephemeral_app_name`, `ge_agent_resource` (ADK), `evaluation_run_ids` (GECX), `expected_evaluator_sa`, and `evals_tree_sha256`.
- Name every ephemeral `[CI]` Sandbox resource with `[CI] PR-<pr_number>-<sha7>` so CI readback binds it to the exact PR and commit.
- Never delete a passing PR's `[CI]` ephemeral resource before GitHub Actions verifies live Sandbox APIs (CES `evaluationRuns`, Vertex AI `reasoningEngines`, or Discovery Engine `agents`).
- Always delete failed or intermediate iteration resources in a `finally` block.
- Rely on the CI workflow `if: always()` teardown plus the operator-scheduled hourly Janitor SA (`4h` TTL) for deterministic cleanup.
- source: https://cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rest

## 3. Strict Synthetic Data Rule
- Use only synthetic fixtures inside `evals/` and Sandbox tests.
- Never copy customer PII (CPF, phone numbers, email addresses, card numbers, or call audio) into any repository or Sandbox bucket.
- source: https://cloud.google.com/architecture/framework/security
