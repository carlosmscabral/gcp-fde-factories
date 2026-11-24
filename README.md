# gcp-fde-factories

Reusable autonomous software factory packs built on Google Cloud Scion (`v0.4.0-preview.3`) and `scion-frontiers/agent-team` for Google Cloud Forward Deployed Engineers (FDEs).

## Active Packs & Capabilities (`v0.4.0`)

- **Pilot Pack 1 — `packs/gecx` (`v0.4.0`):** Google Cloud Customer Engagement Suite / CX Agent Studio (text and synthetic `BidiRunSession` audio), composing Preston's 13-role `agent-team` hierarchy + `gecx-deployer` + `gecx-eval-tester` + `gecx-kaizen-analyst` (**16 offline prefix-scoped templates**, **11 Hub Skill Bank skills**, dedicated `packs/gecx/compat.yaml`).
- **Pack 2 — `packs/adk` (`v0.1.0`):** Google Agent Development Kit (**`google-adk[eval,a2a]==2.15.0`**) + opinionated container-first root `Dockerfile` deploy + **dual Gemini Enterprise (`GE App`) export and Sandbox registration** (`adkAgentDefinition.provisionedReasoningEngine` and `a2aAgentDefinition.jsonAgentCard` via Discovery Engine `v1alpha`), with **16 `adk-*` templates**, **18 Hub Skill Bank skills** (including all 7 vendored `google/agents-cli v1.15.0` skills), dedicated `packs/adk/compat.yaml`, and split-SA Sandbox gate + dual Janitor.
- **Vertex AI-First Harnesses & Generic Model Tiers:** Biased toward **Vertex AI** by default (`auth_selected_type: vertex-ai`, zero static API keys, `global` endpoint default with regional override) using Scion's evolving generic tier aliases (`small`, `medium`, `large`, `extra-large`) and `thinking_level` (`0–100`) — mapping today to Gemini 4 Neon High (`antigravity-vertex` `extra-large`) and Claude Opus 5.5 (`claude-vertex` `large`), with fail-closed validation for manual **Vertex AI Model Garden** Claude opt-in (`harnesses.claude_model_garden_enabled`) and automatic 1P Gemini `cross-model` fallback.
- **Closed-Loop Kaizen Engine (`v0.3.0`, Layer 1 `core-gcp-fde/`):** Scheduled automatically by default on every bootstrapped project (`weekly-kaizen` via `bootstrap-hub-project.sh apply`, opt-out via `kaizen.enabled: false`). Combines 0-token telemetry collection (`kaizen_collect.py`), automated post-merge proposal verification (`kaizen_verifier.py` via `Kaizen-Ref:` trailers, `verified_pass` / `rollback_triggered` / `invalidated_regression`), and `kaizen-analyst` (`hub_role: baseline`) enforcing the 4-Step Intervention Ladder. *(Tier-B GCP Cloud Monitoring/Logging telemetry is opt-in via `--enable-gcp-obs --gcp-obs-json`.)*
- **Dynamic Brownfield Onboarding (`v0.4.0`, Layer 3 `.factory/`):** `scion-defaults`-inspired 0-token static scanner and Day-2 drift detector (`core-gcp-fde/scripts/factory_onboard.py`), portable PO `/grill-me` skill (`core-gcp-fde/skills/factory-onboard/SKILL.md`, including Vertex AI harness/model tuning), deterministic Readiness Gate, atomic non-destructive `AGENTS.md` merge, and conditional digest-pinned `.factory/Dockerfile.customer` emission.
- **Frozen Skeleton:** `packs/agent-platform` remains frozen for a later release.
- **Template Starter:** `packs/_template-pack` provides a validated starter skeleton for future domain packs.

## Quickstart

1. Install Python 3.12 dependencies into `.venv`:
   ```bash
   uv venv .venv --python 3.12
   uv pip install --python .venv/bin/python -e ".[dev]"
   ```
2. Run all static contract, lockfile, context-budget, and clean-room sanitization checks:
   ```bash
   ./build.sh --check packs/gecx
   ./build.sh --check packs/adk
   ./build.sh --check packs/_template-pack
   ```
3. Run the unit test suite (36 offline security, Kaizen, brownfield, ADK/GE, and bootstrap tests):
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
     --toolchain-manifest packs/adk/toolchain-manifest.json --json
   ```

## Guides & Specifications

- **Formal Spec (`v0.3.0` Kaizen & `v0.4.0` Brownfield Onboarding):** [docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md](docs/specs/SPEC_KAIZEN_AND_BROWNFIELD_ONBOARDING.md).
- **ADK Pack & Gemini Enterprise Export Guide:** [packs/adk/README.md](packs/adk/README.md).
- **Agent Authoring & Day-2 Operations:** [docs/AGENT_AUTHORING_AND_OPERATIONS.md](docs/AGENT_AUTHORING_AND_OPERATIONS.md).
- **Infrastructure & Release Kit Walkthrough:** [docs/HANDS_ON_WALKTHROUGH.md](docs/HANDS_ON_WALKTHROUGH.md) + `./scripts/hands-on-walkthrough.sh`.
- **Customer Landing Zone Requirements (including Org Policies, Vertex AI Model Garden & VPC-SC):** [docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md](docs/CUSTOMER_LANDING_ZONE_REQUIREMENTS.md).

## Three-Stage Customer Deployment

1. **Stage 01 (`deploy/01-landing-zone`):** Customer Platform/SecOps provisions networking (custom or Shared VPC), Artifact Registry, least-privilege Service Accounts with additive IAM, explicit non-wildcard Sandbox Custom Roles (`enable_gecx_sandbox_roles`, `enable_adk_sandbox_roles`, `sandboxEvaluatorPredict`, and optional `enable_kaizen_gcp_obs`), and the Inference Project budget. Exports `landing-zone-outputs.json`.
2. **Stage 02 (`deploy/02-factory-runtime`):** Platform or FDE deploys either `lite-vm` (Shielded VM with zero public IP) or `ha-gke` (delegating to the official Scion Terraform module).
3. **Stage 03 (`deploy/03-hub-bootstrap`):** Customer principal runs `stage-release-kit.sh` (`--mode rebuild` default or `--mode mirror` via `crane`), runs `bootstrap-hub-project.sh` (`preflight -> plan -> backup -> apply`), and starts `coordinator` on Day 1. `apply` automatically registers `weekly-kaizen` on every project unless explicitly disabled.

## Architecture Principles

- Every external skill URI pins to a 40-character Git commit SHA and SHA-256 digest in `skills.lock`.
- Every specialist template composes deterministically at build time from `base_role`, `core-gcp-fde` delta, and bounded pack delta without editing `vendor/agent-team/` or `vendor/agents-cli/`.
- Every Release Kit ships zero external URIs, prefix-scoped templates and Vertex AI harness-config bundles, full-tree skill SHA-256 hashes, and safe `--out` overwrite guards.
- Every customer PR Verdict passes deterministic anti-forgery verification against live Sandbox APIs (CES `evaluationRuns`, Vertex AI `reasoningEngines`, or Discovery Engine `agents`) in GitHub Actions.
