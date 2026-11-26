# ADR-016: Structured 6-Pillar Onboarding, Knowledge Plane, Optional No-Sandbox Landing Zone, and Generic Software Pack (`packs/generic`)

- **Status:** Accepted (amends [ADR-008](ADR-008-adopt-first-brownfield-onboarding.md) and [ADR-015](ADR-015-cognitive-brownfield-adaptation-and-contract-validators.md))
- **Date:** 2026-11-25
- **Linked Invariants:** [INV-12](../INVARIANTS.md#inv-12-non-destructive-brownfield-onboarding-and-config-schema), [INV-17](../INVARIANTS.md#inv-17-generic-pack-knowledge-plane-and-safe-coordinator-bootstrap)
- **Triggered By:** Release `v0.6.0` (`contrafile`) review of onboarding depth, multi-pack selection, CI-only Landing Zones, and Day-0 Coordinator bring-up

## Context

In `v0.5.0` (`bife`), `core-gcp-fde/skills/factory-onboard/SKILL.md` spanned 32 lines and supported only `packs/adk` and `packs/gecx`.
Teams onboarding arbitrary software repositories (APIs, web apps, CLIs, libraries, or monorepos) lacked a lean generic pack, narrow Cloud Run Sandbox roles, an optional no-Sandbox CI-only Landing Zone mode, and a structured `/grill-me` question bank.
Three operational gaps also surfaced during live `v0.5.0` operation:

1. Onboarding relied on free-form LLM questioning instead of a declarative 6-pillar question bank, evidence-based role curation, and pre-filled draft profiles.
2. Emitting `.factory/knowledge-index.yaml` did not materialize editable Knowledge Plane files (`.factory/knowledge/*`), initial Wave-1 tasks, or a deterministic link validator (`kp-check`).
3. Stage 03 (`bootstrap-hub-project.sh apply`) synced all pack templates unconditionally and did not bring up the lead Coordinator agent at the end of onboarding.

## Decision

1. **Introduce `packs/generic` (`sw-*`) on top of `scion-frontiers/agent-team` (SEP) and `core-gcp-fde-base`:**
   - `packs/generic` ships the 13 `scion-frontiers/agent-team` roles plus `kaizen-analyst` and `generic-deployer` (15 `sw-*` templates) using the existing `pack.schema.json` and `release_kit.py` pipeline.
   - `packs/generic/Dockerfile` extends `core-gcp-fde-base` without ADK or CES dependencies and installs root-owned `0555` gate scripts under `/opt/generic-factory/`. Customer repositories add stack runtimes via `.factory/Dockerfile.customer`.
   - `packs/generic/scripts/generic_sandbox_gate.py` reads `commands` and `deploy_target` from `.factory/factory-profile.yaml` (or `--base-ref` to prevent PR self-certification), executes scrubbed Level 1 offline checks, and enforces fail-closed Level 2 E2E checks whenever `deploy_target` differs from `none`.
   - `packs/generic/scripts/sandbox_janitor.py` sweeps expired `[CI]` / `factory_ci=true` Cloud Run Sandbox services to uphold `INV-08`.
2. **Add optional no-Sandbox CI-only Landing Zone and narrow generic Sandbox IAM in Stage 01:**
   - `deploy/01-landing-zone/variables.tf` adds `enable_sandbox_project` (default `true`) and `enable_generic_sandbox_roles` (default `false`).
   - When `enable_sandbox_project` is `false` (exceptional pure-CI or `deploy_target: none` topologies), Stage 01 omits Sandbox SAs and routes the Cloud Build staging bucket to `hub_project_id`.
   - When `enable_sandbox_project` and `enable_generic_sandbox_roles` are `true`, `deploy/01-landing-zone/iam_generic.tf` provisions narrow zero-wildcard Cloud Run and Cloud Build Sandbox custom roles (`genericSandboxDeployer`, `genericSandboxEvaluator`, `genericSandboxJanitor`).
3. **Add declarative 6-pillar `/grill-me`, draft profiles, and evidence-based role curation:**
   - Store the 6-pillar interview bank in `core-gcp-fde/data/grill-questions.yaml` with `why_we_ask`, `challenge_prompt`, `field_path`, and pack/track filters.
   - Add `scripts/lib/onboard_stack_detectors.py` alongside `scripts/lib/onboard_parsers.py` to detect Rust, Gradle, Docker, Kubernetes, Cloud Run, frontend frameworks, and monorepos (`nx`, `turbo`, `pnpm-workspace`) without following symlinks.
   - Add `scripts/lib/onboard_questions.py` and `scripts/lib/onboard_roles.py` to recommend a pack, propose enabled and disabled SEP roles with repository evidence, size `reviewer_replicas` when `max_wip >= 4`, and emit a pre-filled draft YAML via `scan --emit-draft`.
4. **Materialize a symlink-safe, zero-clobber Knowledge Plane, Wave-1 backlog, and fail-closed `kp-check`:**
   - Add `scripts/lib/onboard_kp.py` and `scripts/lib/onboard_hub_config.py` to pre-validate every target path against symlink escapes, preserve custom `.factory/Dockerfile.customer*` and existing `.factory/knowledge/*` / `.factory/waves/wave-1.yaml` files unless `--force-knowledge` is passed, and commit outputs via temp-file `os.replace`.
   - Add `factory_onboard.py kp-check --repo <dir>` to require canonical Knowledge Plane files, verify links with symlink guards, enforce regex word-boundary `REQ-NNN` checks, reject duplicate wave task IDs, and fail closed on unknown `REQ-NNN` references.
   - When `git_flow.ci_platform` differs from `github-actions`, treat `.factory/waves/wave-1.yaml` as the Coordinator-managed seed queue while workers track live status via Scion notifications and `/scion-volumes/scratchpad/wave-state.jsonl`.
5. **Filter templates by `roster` and launch the lead Coordinator safely in Stage 03:**
   - `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply` skips templates listed in `roster.disabled_roles` and skips Deployer/Evaluator SA registration when `deploy_target` is `none` or `mode` is `ci-only`.
   - Stage 03 never passes `-w <monorepo.subdir>` on `scion start` so `.factory/` and `AGENTS.md` stay mounted at `/workspace`.
   - Auto-start activates on `v0.6.0+` repositories carrying `.factory/coordinator-bootstrap-brief.md` (unless `--no-start-coordinator` is passed or `coordinator` is disabled), verifies idempotency fail-closed via `scion --format json list`, and starts `<coordinator_agent>` (`--role full`) in PO-gated standby mode.

## Consequences

- Teams can onboard ADK agents, GECX agents, or arbitrary brownfield software repositories through one unified `factory-onboard` flow, including pure-CI Landing Zones without a Sandbox project.
- Modular Python libraries keep every module below 300 lines with zero duplicated pack engine.
- Every `v0.6.0+` onboarded factory starts with a live lead Coordinator visible in the Scion Web UI Agents Graph without regressing `v0.5.0` repos or risking duplicate spawns.

## Enforcement

- `core-gcp-fde/data/grill-questions.yaml` and `core-gcp-fde/skills/factory-onboard/SKILL.md`
- `core-gcp-fde/scripts/factory_onboard.py`
- `scripts/lib/{io_utils,onboard_stack_detectors,onboard_roles,onboard_questions,onboard_kp,onboard_hub_config,onboard_scanner,onboard_emitter}.py`
- `schemas/factory-profile.schema.json`, `schemas/hub-project.schema.json`, and `canaries/scion/scion_v0.4.0-preview.3_cli_contract.json`
- `packs/generic/**` and `deploy/01-landing-zone/{variables,apis,finops,iam,iam_generic,outputs}.tf`
- `deploy/03-hub-bootstrap/{parse_hub_project.py,bootstrap-hub-project.sh,stage-release-kit.sh,cloudbuild.yaml}`
- `tests/test_v060_onboarding_and_generic_pack.py`
