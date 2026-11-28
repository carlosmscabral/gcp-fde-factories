---
name: factory-onboard
description: Wave 2 lean 80/20 onboarding skill (1 Hub -> N Factories) with universal <2s Tier-A scan, streamlined 2-block /grill-me (PO + Engineering), lean (5-role) vs full agent-team preset, unified .factory/[<prefix>/]factory.yaml, surgical <6 KB AGENTS.md, LLM Dockerfile.customer 4-rule linter, and unified validate().
---

# Factory Onboard (`Wave 2` — `1 Hub → N Factories`, Lean 80/20 `/grill-me`)

## 0. Separate Phase A (Platform / Hub Setup, 1×) from Phase B (Factory Onboarding, N×)
- **Phase A (Platform / Hub Setup — run ONCE per organization or environment):**
  - Provision Stage 01 GCP Landing Zone (`deploy/01-landing-zone`), Stage 02 Scion Hub (`lite-vm` or `ha-gke`), and Hub-global settings (GitHub App in Hub Admin UI `/admin/server-config`, `hub.admin_managed_brokers`, and optional External Delta Watcher). See `docs/PLATFORM_HUB_SETUP.md`.
- **Phase B (Per-Factory Onboarding — run N× on the SAME Hub):**
  - Onboard each repository (or each monorepo subproject under `.factory/<prefix>/factory.yaml`) using this skill and Stage 03 `bootstrap-hub-project.sh apply`.
- source: https://github.com/GoogleCloudPlatform/scion

## 1. Run Universal `<2s` Tier-A Scan (Zero `jsonschema` Required)
- Run `python3 core-gcp-fde/scripts/factory_onboard.py scan --repo <TARGET_REPO> --pack <generic|adk|gecx> --roster-preset <lean|full> --emit-draft /tmp/factory-draft.yaml`.
- Inspect `tier_a` returned by `scan`:
  - `monorepo` (5 canonical layouts: JS/TS, JVM, Go, Rust, Python), `git_support_tier` (`native_github` vs `best_effort`), `ci_workflow_pointers`, `task_wrappers`, `version_pins`, `private_registries` (paths only), `env_example_keys` (names only), `local_services`, `ai_files`, `skill_collisions`, `tier_c_warnings`, and blocking workspace hazards (`path@sha256`).
- **Read CI workflows BEFORE asking Engineering questions:** Read the files listed in `tier_a.ci_workflow_pointers` and `tier_a.task_wrappers` to pre-fill exact `build`, `lint`, `test`, and `e2e` commands (empirically ~66% accuracy vs <30% from manifest guessing).
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Run the Streamlined 2-Block `/grill-me` Interview (8 Questions Total)
- Never re-ask facts discovered in `tier_a`. Always record the human approver in `confirmed_by` (empty or placeholder values fail `validate`).
- **Block 1 — Product Owner (4 questions):**
  1. **Mission, Non-Goals, Pack & Monorepo Scope:** 1-sentence mission, explicit non-goals, pack (`generic`/`adk`/`gecx`), and `monorepo.subdir` + `monorepo.agent_prefix` (isolated at `.factory/<prefix>/factory.yaml`).
  2. **Roster Preset (`lean` default vs `full`):**
     - `lean` (5 roles: `coordinator`, `developer`, `code-reviewer`, `security-auditor`, `test-engineer` + deployer/eval only when deploying to sandbox): fastest setup, lowest token burn, ~4.4× error cap. Upgrade to `full` on Day 2 anytime.
     - `full` (`scion-frontiers/agent-team` SEP hierarchy): adds `eng-manager`, `architect`, `investigator`, `doc-writer`, `kaizen-analyst`, `qa-tester`, `web-builder`, `researcher`, `release-notes`. Explicitly warn the PO that `full` takes more time to configure and burns more tokens.
  3. **Invariants, Wave-1 & Optional `wave_0`:** Hard PR invariants, 1–3 Wave-1 vertical-slice tasks, and folding open modernization gaps into `wave_0` (zero empty Day-0 Knowledge Plane placeholders).
  4. **Autonomy, WIP & GitHub Intake:** `autonomy` (`supervised`/`standard`), `max_wip`, and opt-in External Delta Watcher (`factory:ready`, cap 1–3; non-GitHub hosts run in honest `best_effort` manual trigger mode).
- **Block 2 — Engineering Lead (4 questions, pre-filled from CI workflows):**
  5. **Commands & Evaluation Pyramid:** Confirm canonical `build`/`lint`/`test`/`e2e` commands and `not_verifiable_in_sandbox` blind spots.
  6. **Toolchain & `.factory/[<prefix>/]Dockerfile.customer`:** Confirm missing runtimes, version pins, private registries, and `docker-compose`/Testcontainers needs. If custom tools are required, author `.factory/[<prefix>/]Dockerfile.customer` using `ARG BASE_IMAGE` + `FROM ${BASE_IMAGE}`, drop to `USER scion`, run smoke checks for every entry in `toolchain.verify_binaries`, and obey all 4 deterministic linter rules (digest-pinned base, non-root `USER`, zero `curl|sh` or baked secrets/`.env`, post-`USER` smoke checks). For Tier-C edge cases (Bazel, CUDA, Xcode, private Jenkins `@Library`), route honestly to `ci-only` or a manual Dockerfile.
  7. **Cloud Boundary & Vertex Diversity:** Confirm `mode` (`sandbox-direct`/`ci-only`), `deploy_target` (`cloud-run`/`gke`/`agent-engine`/`ces`/`custom`/`none`), and `diversity_profile` (`cross-model` 1P Gemini default, or `cross-vendor` only when Claude Model Garden is already enabled).
  8. **AI Conventions, Collisions & Blocking Hazards:** Synthesize `absorbed_conventions`, resolve any `skill_collisions`, and confirm exact `path@sha256` digests for blocking workspace hazards.
- source: https://github.com/scion-frontiers/agent-team

## 3. Preview (`--dry-run`), Emit (`--pr`), and Run Unified `validate`
- Preview diffs safely without writes: `python3 core-gcp-fde/scripts/factory_onboard.py emit --repo <TARGET_REPO> --profile /tmp/factory-draft.yaml --pack-image <PACK_IMAGE_DIGEST> --dry-run`.
- Emit single `.factory/[<prefix>/]factory.yaml`, surgical `<= 6 KB` `AGENTS.md`, `CLAUDE.md` `@AGENTS.md` bridge (CRLF-safe), `skills/<slug>-repo-conventions/SKILL.md`, and standby brief, then open PR: add `--pr` (plus `--acknowledge-workspace-hazards` after PO/Engineering review).
- Run single fail-closed validator: `python3 core-gcp-fde/scripts/factory_onboard.py validate --repo <TARGET_REPO> [--config .factory/<prefix>/factory.yaml]`. Confirm `"ok": true` (verifies schema, human `confirmed_by`, `AGENTS.md <= 6 KB`, zero broken links, zero skill collisions, and strict 4-rule Dockerfile lint).
- source: https://cloud.google.com/architecture/framework/operational-excellence

## 4. Merge PR and Reconcile via Stage 03 (`bootstrap-hub-project.sh apply`)
- Merge the onboarding PR into `origin/<base_branch>` first (Stage 03 fails closed if `.factory/[<prefix>/]factory.yaml` is not landed remotely).
- Run `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply --kit <kit> --hub <url> --landing-zone <outputs.json> --repo <TARGET_REPO> [--config .factory/<prefix>/factory.yaml]`.
- If `toolchain.dockerfile` is declared, Stage 03 lints it fail-closed, builds it via Cloud Build, runs `toolchain.verify_binaries` as non-root `scion`, and pins the resulting `@sha256` digest into a factory-isolated harness-config so sibling factories on the same Hub never collide.
- source: https://github.com/GoogleCloudPlatform/scion
