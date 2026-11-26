---
name: factory-onboard
description: Day-0 brownfield and greenfield onboarding skill (ADR-008, ADR-015, ADR-016) with Factory Pack selection (adk, gecx, generic), 0-token scan + draft YAML, 6-pillar /grill-me interview, SEP role curation, zero-clobber Knowledge Plane + kp-check, and safe Coordinator startup.
---

# Factory Onboard (`v0.6.0` — Multi-Pack 6-Pillar `/grill-me`, Knowledge Plane, and Coordinator Bring-Up)

## 1. Choose the Factory Pack Style and Run Zero-Token Discovery
- Ask the Product Owner (PO) which Factory Pack fits the repository (confirming the scanner suggestion):
  - `adk` (`adk-*`): Google ADK 2.15+ agents with native `agents-cli` layout and Gemini Enterprise export.
  - `gecx` (`gecx-*`): Conversational Enterprise Service (CES / CX Agent Studio) agents.
  - `generic` (`sw-*`): Any software repository (Go, Node/TypeScript, Python, Java, Rust, frontend, API, CLI, library, or monorepo) built on `scion-frontiers/agent-team` (SEP) + `core-gcp-fde-base` without ADK/CES runtime bloat.
- Run `python3 core-gcp-fde/scripts/factory_onboard.py scan --repo <TARGET_REPO> --pack <adk|gecx|generic> --track <express|complete> --emit-draft /tmp/factory-profile-draft.yaml`.
- Inspect `recommended_pack`, `monorepo`, `frontend_frameworks`, `deploy_signals`, `proposed_roles`, `grill_questions`, and `advisory_findings` returned by `scan`.
- Read pre-existing manifests, CI workflows, AI instruction files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, `.claude/skills/`), and flagged workspace hooks cognitively to synthesize verifiable rules into `absorbed_conventions`.
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Run the Structured 6-Pillar `/grill-me` Interview (One Pillar at a Time)
- Follow the exact filtered questions returned in `scan.grill_questions` (loaded from `core-gcp-fde/data/grill-questions.yaml`) instead of improvising questions.
- Never re-ask static facts already pre-filled in `prefilled_from_scan` or the draft YAML. Never invent business intent, SLOs, requirements, or invariants without PO confirmation.
- Use each question's `why_we_ask` to explain value concisely and apply `challenge_prompt` until every requirement, invariant, and acceptance criterion is testable by a command or diff.
- **Six Pillars:**
  1. **Pack, Scope, and Monorepo:** New vs. existing Hub, pack confirmation, track (`express` ~10 min vs. `complete` ~25 min), and `monorepo.subdir` + `monorepo.agent_prefix` when monorepo signals exist.
  2. **Mission, Requirements, and Invariants (`complete`):** `mission`, `non_goals`, testable `REQ-NNN`, verifiable `invariants`, initial `decisions` (`ADR-NNN`), and `glossary`.
  3. **Stack, Toolchain, and Container:** Confirm canonical `build`/`lint`/`test`/`e2e` commands, `absorbed_conventions`, and missing or unsupported binaries for `.factory/Dockerfile.customer` (+ `-tester` for Playwright/JDK).
  4. **Deploy Target and Cloud Boundary:** Confirm `mode` (`sandbox-direct` vs. `ci-only`). For `packs/generic`, always confirm `deploy_target` (`cloud-run`, `gke`, `custom`, or `none` for libraries/CLIs).
  5. **SEP Team, Capacity, and Models:** Confirm Vertex AI `diversity_profile` (`cross-vendor` requires manual Claude Model Garden opt-in on `inference_project_id`. Otherwise use `cross-model` 1P Gemini tiers), curate `roster.enabled_roles` and `roster.disabled_roles` with explicit reasons from `proposed_roles`, and set `reviewer_replicas: 2` when `max_wip >= 4`.
  6. **Evaluation Pyramid, Wave-1, and Kaizen:** Confirm `evaluation_pyramid` (`l1_offline` plus `l2_sandbox` when `deploy_target != none`), explicit `not_verifiable_in_sandbox` blind spots, initial `waves` (`W1-01`..`W1-05` linked to `REQ-NNN` with SEP size `small`/`chunky`/`large`), and Kaizen cron (`America/Sao_Paulo`).
- source: https://github.com/scion-frontiers/agent-team

## 3. Validate, Emit Zero-Clobber Knowledge Plane, and Check Contracts
- Run `python3 core-gcp-fde/scripts/factory_onboard.py check --profile <profile.yaml>` until `"ready": true` and resolve any sizing warnings.
- Run `python3 core-gcp-fde/scripts/factory_onboard.py emit --repo <TARGET_REPO> --profile <profile.yaml> --pack-image <PACK_IMAGE_DIGEST>`.
  - `emit` atomically writes `.factory/factory-profile.yaml`, `.factory/hub-project.yaml`, `.factory/knowledge-index.yaml`, `.factory/knowledge/*`, `.factory/waves/wave-1.yaml`, `.factory/coordinator-bootstrap-brief.md`, `.factory/modernization-backlog.yaml`, `skills/<slug>-repo-conventions/SKILL.md`, `AGENTS.md` (preserving CRLF and `CLAUDE.md`/`GEMINI.md` parity), and `.gitignore` (`.scion/agents/`).
  - Existing files under `.factory/knowledge/` and `.factory/waves/` are preserved by default on re-emit unless `--force-knowledge` is passed.
- For arbitrary customer runtimes (ADR-015, such as `nx`, `cargo`, or internal CLIs), author or extend `.factory/Dockerfile.customer` on top of the digest-pinned pack image and run `python3 core-gcp-fde/scripts/factory_onboard.py validate-dockerfile --dockerfile .factory/Dockerfile.customer` (advisory by default. Pass `--strict` only when requested).
- Run `python3 core-gcp-fde/scripts/factory_onboard.py kp-check --repo <TARGET_REPO>` to confirm zero broken Knowledge Plane links and valid `REQ-NNN` traceability.
- source: https://cloud.google.com/architecture/framework/operational-excellence

## 4. Sync to Scion Hub and Start the Lead Coordinator in Standby Mode
- Adapt existing CI workflows non-destructively (keeping legacy jobs intact). For repositories outside GitHub Actions (Azure DevOps, GitLab, or local Git), keep `.factory/waves/wave-1.yaml` as the Coordinator's native work queue.
- Run Stage 03 `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply --kit <kit> --hub <url> --landing-zone <outputs.json> --repo <TARGET_REPO>`.
  - Stage 03 skips templates listed in `roster.disabled_roles`, skips Deployer and Evaluator SAs when `deploy_target` is `none` or `mode` is `ci-only`, and idempotently launches the lead Coordinator (`--role full`) using `--task-file .factory/coordinator-bootstrap-brief.md`.
  - The Coordinator starts in PO-gated standby mode, summarizes Wave-1 in Scion Chat, and waits for explicit PO approval before spawning developers or opening pull requests (pass `--no-start-coordinator` in headless CI pipelines).
- source: https://github.com/GoogleCloudPlatform/scion
