# Architectural Invariants

This document lists the non-negotiable invariants enforced by `gcp-fde-factories`.
Every invariant traces to an Architecture Decision Record under [docs/adr/](adr/README.md), an enforcing code path, and an automated check.
If a change breaks an invariant, fix the code or update the linked ADR before merging.

## Invariant Registry

| ID | Invariant | ADR | Enforcement Code | Automated Test |
| :--- | :--- | :--- | :--- | :--- |
| INV-01 | No upstream Scion fork and self-contained offline kits | [ADR-001](adr/ADR-001-four-layer-architecture-and-vendoring.md) | `build.sh`, `scripts/lib/release_kit.py` | `tests/test_release_kit_build.py` |
| INV-02 | Additive IAM only and decoupled stage JSON contracts | [ADR-002](adr/ADR-002-three-stage-deployment-and-project-topologies.md) | `deploy/01-landing-zone/`, `deploy/02-factory-runtime/` | `tests/test_terraform_and_scaffold_parity.py` |
| INV-03 | Zero-PII custom roles without wildcards | [ADR-003](adr/ADR-003-zero-pii-custom-roles-and-split-sa-isolation.md) | `deploy/01-landing-zone/iam.tf` | `tests/test_terraform_and_scaffold_parity.py` |
| INV-04 | Split Service Account separation and Janitor exclusion | [ADR-003](adr/ADR-003-zero-pii-custom-roles-and-split-sa-isolation.md) | `deploy/01-landing-zone/iam.tf`, `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` | `tests/test_terraform_and_scaffold_parity.py` |
| INV-05 | Offline Release Kit integrity and SHA-256 checksums | [ADR-004](adr/ADR-004-offline-release-kits-and-image-separation.md) | `scripts/lib/release_kit.py` | `tests/test_release_kit_build.py` |
| INV-06 | Digest-pinned runtime and harness container images | [ADR-004](adr/ADR-004-offline-release-kits-and-image-separation.md), [ADR-010](adr/ADR-010-scion-hardening-and-pinned-supply-chain.md) | `deploy/03-hub-bootstrap/stage-release-kit.sh`, `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` | `tests/test_release_kit_build.py` |
| INV-07 | Anti-forgery Verdict readback and commit binding | [ADR-005](adr/ADR-005-anti-forgery-verdicts-and-janitor-teardown.md) | `scripts/verify-verdict.py`, `schemas/verdict.schema.json` | `tests/test_verdict_and_gate.py` |
| INV-08 | Ephemeral `[CI]` naming prefix and TTL Janitor teardown | [ADR-005](adr/ADR-005-anti-forgery-verdicts-and-janitor-teardown.md) | `packs/gecx/scripts/sandbox_janitor.py`, `packs/adk/scripts/sandbox_janitor.py` | `tests/test_verdict_and_gate.py`, `tests/test_adk_pack_and_ge_export.py` |
| INV-09 | Vertex AI default routing and generic model tiers | [ADR-006](adr/ADR-006-vertex-ai-generic-tiers-and-fail-closed-claude.md) | `scripts/lib/model_routing.py`, `core-gcp-fde/harness-configs/antigravity-vertex.yaml` | `tests/test_release_kit_build.py` |
| INV-10 | Fail-closed Claude on Vertex preflight validation | [ADR-006](adr/ADR-006-vertex-ai-generic-tiers-and-fail-closed-claude.md) | `deploy/03-hub-bootstrap/parse_hub_project.py`, `deploy/03-hub-bootstrap/bootstrap-hub-project.sh` | `tests/test_release_kit_build.py` |
| INV-11 | Zero-token Kaizen collection and human-gated PRs | [ADR-007](adr/ADR-007-closed-loop-zero-token-kaizen-engine.md) | `core-gcp-fde/scripts/kaizen_collect.py`, `scripts/lib/kaizen_verifier.py` | `tests/test_kaizen_v030.py` |
| INV-12 | Non-destructive brownfield onboarding and config schema | [ADR-008](adr/ADR-008-adopt-first-brownfield-onboarding.md) | `core-gcp-fde/scripts/factory_onboard.py`, `schemas/factory-profile.schema.json` | `tests/test_brownfield_onboard_v040.py` |
| INV-13 | Dockerfile-first ADK packaging and dual GE export | [ADR-009](adr/ADR-009-dockerfile-first-adk-and-dual-ge-export.md) | `packs/adk/repo-scaffold/Dockerfile`, `packs/adk/scripts/ge_export.py` | `tests/test_adk_pack_and_ge_export.py` |
| INV-14 | Pinned Scion release and fail-closed Hub IAM | [ADR-010](adr/ADR-010-scion-hardening-and-pinned-supply-chain.md) | `compat.yaml`, `deploy/02-factory-runtime/lite-vm/cloud-init.tftpl` | `tests/test_schemas_and_lock.py`, `tests/test_terraform_and_scaffold_parity.py` |
| INV-15 | Public clean-room sanitization and secret denylist | [ADR-011](adr/ADR-011-public-clean-room-and-runtime-denylist.md) | `scripts/sanitize-public-check.py`, `scripts/lib/sanitizer.py` | `tests/test_sanitizer.py` |
| INV-16 | Functional E2E qualification and verified teardown | [ADR-012](adr/ADR-012-functional-hillclimbing-e2e-qualification.md) | `docs/HILLCLIMBING_CHARTER.md` | Live E2E Hillclimbing Scorecard |

## Detailed Invariant Specifications

### INV-01: No Upstream Scion Fork and Self-Contained Kits

The repository must not vendor or fork upstream Scion Go source code.
`scripts/lib/release_kit.py` must copy every required `vendor/` and `core-gcp-fde/` policy, skill, schema, and script into each Release Kit so the kit runs without network access to this repository.

### INV-02: Additive IAM and Explicit Stage Contracts

Terraform modules under `deploy/` must never use authoritative IAM resources (`google_project_iam_policy`, `google_project_iam_binding`).
Stage 02 and Stage 03 must read explicit Stage 01 JSON outputs instead of relying on implicit `terraform_remote_state` lookups.

### INV-03: Zero-PII Custom Roles Without Wildcards

Every custom role in `deploy/01-landing-zone/iam.tf` must list explicit permissions only.
No custom role may contain `*`, `contactcenterinsights.*`, or `ces.conversations.*`.
Worker, Deployer, and Evaluator Service Accounts must use explicit `aiplatform.endpoints.predict` (`vertexInferencePredict`) on `inference_project_id` instead of broad `roles/aiplatform.user`.

### INV-04: Split SA Separation and Janitor Exclusion

The factory must separate Worker, Deployer, Evaluator, and Janitor duties across distinct Service Accounts.
The Scion Hub Service Account must never receive `roles/iam.serviceAccountTokenCreator` or GKE `roles/iam.workloadIdentityUser` on `sandbox_janitor`.
`deploy/03-hub-bootstrap/bootstrap-hub-project.sh` must never register `sandbox_janitor` as an assignable Hub identity.

### INV-05: Offline Release Kit Integrity and SHA-256 Checksums

Every built Release Kit must contain a valid `manifest.json` with embedded per-file SHA-256 hashes and a verifiable `skills.lock`.
Every kit must pass `./build.sh --check` without missing templates, skills, or schemas.

### INV-06: Digest-Pinned Runtime and Harness Images

`deploy/03-hub-bootstrap/bootstrap-hub-project.sh` must reject placeholder image refs, unpinned tags without `@sha256:`, and mixed lean CI images when agent harness images are required.
`deploy/03-hub-bootstrap/stage-release-kit.sh` must stamp verified `@sha256:` digests into `manifest.json` and `harness-configs/*/config.yaml`.

### INV-07: Anti-Forgery Verdict Readback and Commit Binding

`scripts/verify-verdict.py` must reject any Verdict whose `commit_sha` does not match the pull request HEAD commit.
When verifying `live-gcp-verified` Verdicts, the verifier must read back the live GCP evaluation run or ReasoningEngine resource under the read-only Evaluator SA.

### INV-08: Ephemeral `[CI]` Naming and Janitor Teardown

Every Sandbox app, ReasoningEngine, or Gemini Enterprise registration created by factory automation must carry the `[CI]` display-name prefix.
Janitor scripts (`packs/gecx/scripts/sandbox_janitor.py` and `packs/adk/scripts/sandbox_janitor.py`) must delete only `[CI]` resources older than the configured TTL and must never delete non-`[CI]` customer resources.

### INV-09: Vertex AI Default and Generic Model Tiers

All default harness configurations (`core-gcp-fde/harness-configs/antigravity-vertex.yaml`, `core-gcp-fde/harness-configs/claude-vertex.yaml`) must route inference through Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=true`, `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION=global`).
Templates, skills, and operational runbooks must reference generic model tier names (`extra-large`, `large`, `medium`, `small`) resolved by `scripts/lib/model_routing.py`.

### INV-10: Fail-Closed Claude on Vertex Preflight

If `cross-vendor` or any `claude-vertex` role is configured while `harnesses.claude_model_garden_enabled` is `false`, `deploy/03-hub-bootstrap/parse_hub_project.py` must fail closed.
If `CLAUDE_CODE_USE_VERTEX=1` is active during `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`, the script must fail closed whenever `ANTHROPIC_VERTEX_PROJECT_ID` is empty.

### INV-11: Zero-Token Kaizen Collection and Human-Gated PRs

`core-gcp-fde/scripts/kaizen_collect.py` must run with zero LLM calls and report explicit `sources_status` values (`ok`, `skipped`, `error`) for each telemetry source.
The `kaizen-analyst` agent must open pull requests for human review and must never push directly to `main`.

### INV-12: Non-Destructive Brownfield Onboarding and Config Schema

`core-gcp-fde/scripts/factory_onboard.py` must never move, rename, or delete existing customer source files.
All generated `.factory/factory-profile.yaml` and `.factory/hub-project.yaml` files must validate against `schemas/factory-profile.schema.json` and `schemas/hub-project.schema.json`.

### INV-13: Dockerfile-First ADK Packaging and Dual GE Export

`packs/adk` must package agents via a non-root `Dockerfile` and must not default to `cloudpickle` serialization.
`packs/adk/scripts/ge_export.py` must emit `ge_export_manifest.json` (with `dry_run_curl` and SHA-256 digest) and `ge_registration_payload.json` targeting Discovery Engine `v1alpha`.

### INV-14: Pinned Scion Release and Hardened Hub IAM

`compat.yaml` and Stage 02 templates must pin an exact Scion release tag and SHA-256 checksum.
Every Hub runtime must enable `policytroubleshooter.googleapis.com` and configure `default_gcp_identity_mode=block`, `default_agent_role=baseline`, `gcp_iam_check_mode=enforce`, and `gcp_iam_deny_unknown_policy=fail-open` for project-scoped Hub SAs (or `fail-closed` with org-level `roles/iam.denyReviewer`).

### INV-15: Public Clean-Room Sanitization and Secret Denylist

`scripts/sanitize-public-check.py` must exit 0 across all tracked files on every commit.
No customer names, personal project IDs, billing IDs, corporate email domains, or internal links may appear in tracked repository files.

### INV-16: Functional E2E Qualification and Clean Teardown

Every major factory runtime profile (Lite VM and GKE) and pack (`gecx` and `adk`) must qualify against live Google Cloud projects using [HILLCLIMBING_CHARTER.md](HILLCLIMBING_CHARTER.md).
Every qualification run must delete all ephemeral projects, containers, and test repositories after collecting evidence.
