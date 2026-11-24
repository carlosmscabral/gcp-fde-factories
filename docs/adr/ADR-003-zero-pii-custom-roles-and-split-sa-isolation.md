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
   - `vertexInferencePredict` (`aiplatform.endpoints.predict` only on `inference_project_id`, replacing broad `roles/aiplatform.user` on `worker` and bound to `worker`, `deployer`, and `eval` alongside `roles/serviceusage.serviceUsageConsumer`).
   - `gecxSandboxDeployer` (metadata read plus app, agent, tool, guardrail, and evaluation write).
   - `gecxSandboxEvaluator` (metadata read plus evaluation execution and tool test execution, zero writes).
   - `gecxSandboxJanitor` (app list, get, delete, and operations read only).
   - `sandboxEvaluatorPredict` (`aiplatform.endpoints.predict` only on `sandbox_project_id` when distinct from `inference_project_id`).
   - `adkSandboxDeployer`, `adkSandboxEvaluator`, and `adkSandboxJanitor` (explicit `aiplatform.reasoningEngines.*`, `discoveryengine.agents.*`, `cloudbuild.builds.*`, and `run.services.*` permissions for Dockerfile-first deploys).
2. Forbid `contactcenterinsights.*`, `ces.conversations.*`, and `*` wildcard permissions in all custom roles.
3. Isolate duties across dedicated Service Accounts: `hub`, `iap`, `worker`, `deployer`, `eval`, `janitor`, `builder`, and optional read-only `kaizen`.
4. Never grant the Scion Hub `roles/iam.serviceAccountTokenCreator` or GKE `roles/iam.workloadIdentityUser` on `sandbox_janitor`, and never register `sandbox_janitor` on the Hub.
5. Materialize service agents via `google_project_service_identity` before binding IAM (`ces.googleapis.com` for staging bucket `roles/storage.objectUser`, and `run.googleapis.com` plus `aiplatform.googleapis.com` for `roles/artifactregistry.reader` on `hub_project_id` alongside `sandbox_deployer`).
6. Grant `release_builder` staging bucket read and write access (`roles/storage.objectAdmin` and `roles/storage.bucketViewer`) for Cloud Build source and log staging.

## Consequences

- Autonomous coding agents (`worker` SA) cannot deploy to or read from the Sandbox project.
- Evaluators (`eval` SA) cannot modify apps or forge evaluation setups before running tests.
- No factory identity can read customer call recordings, conversation transcripts, or Contact Center Insights data.

## Enforcement

- `deploy/01-landing-zone/iam.tf`
- `deploy/01-landing-zone/finops.tf`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_terraform_and_scaffold_parity.py`
