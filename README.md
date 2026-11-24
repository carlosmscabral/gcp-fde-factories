# gcp-fde-factories

Reusable autonomous software factory packs built on Google Cloud Scion (`v0.4.0-preview.3`) and `scion-frontiers/agent-team` for Google Cloud Forward Deployed Engineers (FDEs).

## Active Packs & Capabilities (`v0.4.0`)

- **Pilot Pack 1 — `packs/gecx` (`v0.4.0`):** Google Cloud Customer Engagement Suite / CX Agent Studio (text and synthetic `BidiRunSession` audio), composing Preston's 13-role `agent-team` hierarchy + `gecx-deployer` + `gecx-eval-tester` + `gecx-kaizen-analyst` (**16 offline prefix-scoped templates**, **11 Hub Skill Bank skills**).
- **Pack 2 — `packs/adk` (`v0.1.0`):** Google Agent Development Kit (ADK) + Vertex AI Agent Engine + **dual Gemini Enterprise (`GE App`) export and Sandbox registration** (`adkAgentDefinition.provisionedReasoningEngine` and `a2aAgentDefinition.jsonAgentCard` via Discovery Engine `v1alpha`), with **16 `adk-*` templates**, **11 Hub Skill Bank skills**, modular `repo-scaffold/`, and split-SA Sandbox gate + Janitor.
- **Closed-Loop Kaizen Engine (`v0.3.0`, Layer 1 `core-gcp-fde/`):** 0-token telemetry collector (`core-gcp-fde/scripts/kaizen_collect.py`), `schemas/kaizen-snapshot.schema.json`, and `kaizen-analyst` (`hub_role: baseline`) enforcing a 4-step Intervention Ladder, surgical prompt diffs with rollback criteria, and Option A `researcher` delegation via `coordinator`.
- **Dynamic Brownfield Onboarding (`v0.4.0`, Layer 3 `.factory/`):** `scion-defaults`-inspired 0-token static scanner and drift detector (`core-gcp-fde/scripts/factory_onboard.py`), portable PO `/grill-me` skill (`core-gcp-fde/skills/factory-onboard/SKILL.md`), deterministic Readiness Gate, non-destructive delimited `AGENTS.md` merge, and conditional `FROM <pack-image>` `.factory/Dockerfile.customer` emission.
- **Frozen Skeleton:** `packs/agent-platform` remains frozen for a later release.
- **Template Starter:** `packs/_template-pack` defines the canonical skeleton for future domain packs.

## Quickstart

1. Install Python 3.12 dependencies into `.venv`:
   ```bash
   uv venv .venv --python 3.12
   uv pip install --python .venv/bin/python -e ".[dev]"
   ```
2. Run all static contract, lockfile, context-budget, and public sanitization checks:
   ```bash
   ./build.sh --check packs/gecx
   ./build.sh --check packs/adk
   ```
3. Run the unit test suite:
   ```bash
   ./build.sh --test
   ```
4. Build self-contained offline Release Kits for customer delivery:
   ```bash
   ./build.sh --release-kit packs/gecx --out /tmp/gecx-kit
   ./build.sh --release-kit packs/adk --out /tmp/adk-kit
   ```
5. Validate or export a Gemini Enterprise (`GE App`) registration bundle for an ADK repo:
   ```bash
   .venv/bin/python packs/adk/scripts/ge_export.py export \
     --manifest packs/adk/repo-scaffold/ge_manifest.json \
     --out /tmp/ge-export
   ```
6. Scan an existing brownfield repository before Day-0 onboarding (0 tokens):
   ```bash
   .venv/bin/python core-gcp-fde/scripts/factory_onboard.py scan \
     --repo /path/to/customer-repo \
     --toolchain-manifest packs/adk/toolchain-manifest.json
   ```

## Guides & Specifications

- **Formal Spec (`v0.3.0` Kaizen & `v0.4.0` Brownfield Onboarding):** [docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md](docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md).
- **ADK Pack & Gemini Enterprise Export Guide:** [packs/adk/README.md](packs/adk/README.md).
- **Agent Authoring & Day-2 Operations:** [docs/AGENT_AUTHORING_AND_OPERATIONS.md](docs/AGENT_AUTHORING_AND_OPERATIONS.md) (how specialists are composed, how to create/edit agents, and how to run `packs/gecx` end-to-end to build a GECX agent).
- **Infrastructure & Release Kit Walkthrough:** [docs/HANDS_ON_WALKTHROUGH.md](docs/HANDS_ON_WALKTHROUGH.md) + `./scripts/hands-on-walkthrough.sh`.
- **Customer Landing Zone Requirements (including Org Policies & VPC-SC):** [docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md](docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md).

## Three-Stage Customer Deployment

1. **Stage 01 (`deploy/01-landing-zone`):** Customer Platform/SecOps provisions networking (custom or Shared VPC), Artifact Registry, least-privilege Service Accounts with additive IAM, explicit non-wildcard Sandbox Custom Roles (GECX by default, plus optional `enable_adk_sandbox_roles` for ADK/GE and `enable_kaizen_gcp_obs` for Tier-B Kaizen observability), and the Inference Project budget. Exports `landing-zone-outputs.json`.
2. **Stage 02 (`deploy/02-factory-runtime`):** Platform or FDE deploys either `lite-vm` (Shielded VM with zero public IP) or `ha-gke` (delegating to the official Scion Terraform module).
3. **Stage 03 (`deploy/03-hub-bootstrap`):** Customer principal runs `bootstrap-hub-project.sh` (`preflight -> plan -> backup -> apply`) and starts `coordinator` on Day 1.

## Architecture Principles

- Every external skill URI pins to a 40-character Git commit SHA and SHA-256 digest in `skills.lock`.
- Every specialist template composes deterministically at build time from `base_role` plus a bounded pack delta without editing `vendor/agent-team/`.
- Every Release Kit ships zero external URIs and supports both pre-built mirror staging (`stage-release-kit.sh`) and internal rebuild (`cloudbuild.yaml`).
- Every customer PR Verdict passes deterministic anti-forgery verification against live Sandbox APIs (CES `evaluationRuns`, Vertex AI `reasoningEngines`, or Discovery Engine `agents`) in GitHub Actions.
