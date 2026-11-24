# ADR-003: Zero-PII Custom Roles and Split Service Accounts

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-03](../INVARIANTS.md#inv-03-zero-pii-custom-roles-without-wildcards), [INV-04](../INVARIANTS.md#inv-04-split-sa-separation-and-janitor-exclusion)

## Context

Live IAM inspection during Gate 0 proved that all eleven predefined `roles/ces.*` roles inherit 79 `contactcenterinsights.*` permissions and `ces.conversations.*` permissions.
Those permissions expose customer call transcripts and recordings.
Meanwhile, `roles/ces.appEditor` omits write permissions for agents, tools, toolsets, and guardrails.
Allowing a single identity to write agent code, deploy apps, run evaluations, and delete environments violates separation of duties.

## Decision

1. Define explicit non-wildcard Custom Roles in `deploy/01-landing-zone/iam.tf`:
   - `gecxSandboxDeployer` (metadata read plus app, agent, tool, guardrail, and evaluation write)
   - `gecxSandboxEvaluator` (metadata read plus evaluation execution and tool test execution, zero writes)
   - `gecxSandboxJanitor` (app list, get, delete, and operations read only)
   - `sandboxEvaluatorPredict` (`aiplatform.endpoints.predict` only, replacing broad `roles/aiplatform.user` on Sandbox)
   - `adkSandboxDeployer`, `adkSandboxEvaluator`, and `adkSandboxJanitor` (explicit `aiplatform.reasoningEngines.*` and `discoveryengine.agents.*` permissions)
2. Forbid `contactcenterinsights.*`, `ces.conversations.*`, and `*` wildcard permissions in all custom roles.
3. Isolate duties across dedicated Service Accounts: `hub`, `iap`, `worker`, `deployer`, `eval`, `janitor`, `builder`, and optional read-only `kaizen`.
4. Never grant the Scion Hub `roles/iam.serviceAccountTokenCreator` on `sandbox_janitor`, and never register `sandbox_janitor` on the Hub.
5. Grant the CES Service Agent `roles/storage.objectUser` on the ephemeral staging bucket so `cxas` staging imports succeed.

## Consequences

- Autonomous coding agents (`worker` SA) cannot deploy to or read from the Sandbox project.
- Evaluators (`eval` SA) cannot modify apps or forge evaluation setups before running tests.
- No factory identity can read customer call recordings, conversation transcripts, or Contact Center Insights data.

## Enforcement

- `deploy/01-landing-zone/iam.tf`
- `deploy/01-landing-zone/finops.tf`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_terraform_and_scaffold_parity.py`
