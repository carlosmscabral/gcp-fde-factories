# ADR-013: Cross-Project ADC Quota Routing and Same-Project ADK Runtime SA

- **Status:** Accepted
- **Date:** 2026-11-24
- **Linked Invariants:** INV-02, INV-03, INV-09, INV-13
- **Triggered By:** Live 3-project Hillclimbing Round 2 (`HC-2026-11-24-02`, findings `HC02-F8`, `HC02-F10`, `HC02-F12`, `HC02-F13`)

## Context

In the 3-project enterprise topology (`hub_project_id != inference_project_id != sandbox_project_id`), live testing uncovered three cross-project platform constraints that offline tests and single-project sandboxes do not trigger:

1. Antigravity CLI `1.5.14` in `AGY_ADC_AUTH=true` mode routes Vertex AI inference using the ADC `quotaProject` rather than `GOOGLE_CLOUD_PROJECT` or `settings.json`. Without `GOOGLE_CLOUD_QUOTA_PROJECT`, GKE pods route inference to `hub_project_id` (where Vertex AI is disabled) and VM deployer or evaluator containers route inference to `sandbox_project_id` (where deployers hold no predict role).
2. Enterprise Google Cloud organizations enforce `constraints/iam.disableCrossProjectServiceAccountUsage`, which blocks attaching `worker@inference_project_id` to Cloud Run services or Vertex AI Agent Engine runtimes in `sandbox_project_id`.
3. Discovery Engine `v1alpha` and Vertex AI `ReasoningEngine` APIs return resource names containing the numeric project number (`projects/<number>/...`) rather than the string project ID.

## Decision

1. **Inject `GOOGLE_CLOUD_QUOTA_PROJECT` in Stage 03:** `deploy/03-hub-bootstrap/parse_hub_project.py` and `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` always set `GOOGLE_CLOUD_QUOTA_PROJECT=<inference_project_id>` alongside `GOOGLE_CLOUD_PROJECT` in rendered harness configs and project environment variables (`injectionMode=always`).
2. **Provision a Same-Project ADK Runtime SA in Stage 01:** When `enable_adk_sandbox_roles = true`, `deploy/01-landing-zone/iam.tf` creates `<prefix>-adk-runtime@<sandbox_project_id>`, grants `sandbox_deployer` `roles/iam.serviceAccountUser` on it, grants it `vertexInferencePredict` + `serviceUsageConsumer` on `inference_project_id` and `roles/artifactregistry.reader` on `hub_project_id`, and assigns it zero write permissions in `sandbox_project_id`.
3. **Require Explicit Numeric Project Number Matching:** `packs/adk/scripts/lib/ge_payload.py`, `packs/adk/scripts/ge_export.py`, and `packs/adk/scripts/adk_sandbox_gate.py` accept `--quota-project-number` / `--sandbox-project-number` (or `SANDBOX_PROJECT_NUMBER`, exported from Stage 01 `sandbox_project_number`) so numeric GCP resource paths pass validation while cross-project targets remain blocked.
4. **Add Dedicated GKE Node SA and `discoveryengine.agents.manage`:** Stage 01 provisions `<prefix>-gke-node@<hub_project_id>` when `enable_gke_api = true` and includes `discoveryengine.agents.manage` in `adkSandboxDeployer` and `adkSandboxJanitor`.

## Consequences

- All three assignable personas (`worker`, `deployer`, `eval`) execute real Vertex AI LLM turns against `inference_project_id` on both Lite VM and GKE without relaxing IAM isolation on `hub` or `sbx`.
- Deployed ADK workloads in `sandbox_project_id` comply with `constraints/iam.disableCrossProjectServiceAccountUsage` while keeping zero write access to Sandbox control planes.
- Operators deploying to hardened organizations follow [deploy/ENTERPRISE_PREREQUISITES.md](../../deploy/ENTERPRISE_PREREQUISITES.md) as a single Day-0 checklist.

## Enforcement

- `deploy/01-landing-zone/iam.tf` and `deploy/01-landing-zone/outputs.tf` (`gke_node`, `adk_runtime`, `sandbox_project_number`, `vpc_name`)
- `deploy/03-hub-bootstrap/parse_hub_project.py` and `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `packs/adk/scripts/lib/ge_payload.py`, `packs/adk/scripts/ge_export.py`, and `packs/adk/scripts/adk_sandbox_gate.py`
- `tests/test_adk_pack_and_ge_export.py` and `tests/test_bootstrap_and_kaizen.py`
