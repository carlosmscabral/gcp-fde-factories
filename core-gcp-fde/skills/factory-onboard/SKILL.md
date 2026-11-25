---
name: factory-onboard
description: Day-0 brownfield onboarding skill (ADR-008 + ADR-015) combining 0-token repo scanning, cognitive authoring (custom binaries, AI rules, CI), 2-track PO /grill-me interview, and advisory Day-0 contract validators.
---

# Factory Onboard (`v0.5.0` — Cognitive Authoring + Advisory Day-0 Validators)

## 1. Detect Existing vs. New Hub, Scan Statically, and Read Cognitively
- Ask whether this repository targets a **New Scion Hub** (Stages 01, 02, and 03) or an **Existing Scion Hub** (skip Stages 01 and 02 and run Stage 03 `apply --repo`).
- Run `python3 core-gcp-fde/scripts/factory_onboard.py scan --repo <TARGET_REPO> --toolchain-manifest packs/<pack>/toolchain-manifest.json` first for zero-token baseline facts.
- Go beyond static regexes: cognitively read repository manifests, CI workflows, pre-existing AI files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, `.claude/skills/`), and any flagged workspace hooks (`.claude/settings*.json`, `.githooks/`, `.husky/`).
- Synthesize concrete, verifiable customer rules into `absorbed_conventions` and present detected facts plus any non-blocking `advisory_findings` in a short confirmation table.
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Conduct the 2-Track PO Interview (`/grill-me`) One Topic at a Time
- Never re-ask static facts already discovered. Never invent business intent, SLOs, autonomy rules, or acceptance criteria without explicit PO confirmation.
- Challenge vague answers until every requirement or invariant is verifiable by a diff or command.
- **Vertex AI Harnesses & Models:** use Scion generic semantic tiers (`small`, `medium`, `large`, `extra-large`) and `thinking_level` (`0–100`). Confirm whether Anthropic Claude was manually enabled in Vertex AI Model Garden on `inference_project_id`:
  - **Enabled:** propose `diversity_profile: cross-vendor` with `harnesses.claude_model_garden_enabled: true` (`antigravity-vertex` author, `claude-vertex` reviewer/auditor).
  - **Not enabled:** propose `diversity_profile: cross-model` with `harnesses.claude_model_garden_enabled: false` (1P Gemini only).
- Offer two tracks:
  - **Express (~10 min):** confirm scan facts, `mode`, Vertex AI harnesses/models, `autonomy`, limits, Kaizen schedule (`America/Sao_Paulo`), in-place doc index, and `modernization-backlog.yaml`.
  - **Complete (~25 min):** Express plus guided `mission`, `non_goals`, testable `REQ-NNN` requirements, verifiable `invariants`, and `evaluation_pyramid` targets.
- source: https://github.com/scion-frontiers/agent-team

## 3. Author Custom Overlays, Validate Advisory Contracts, and Sync to Hub
- Save the confirmed profile YAML and run `python3 core-gcp-fde/scripts/factory_onboard.py check --profile <profile.yaml>` until `"ready": true`.
- Run `python3 core-gcp-fde/scripts/factory_onboard.py emit --repo <TARGET_REPO> --profile <profile.yaml> --pack-image <PACK_IMAGE_DIGEST>` to emit `.factory/` files, preserve legacy AI files/CRLF, and ensure `.scion/agents/` is in `.gitignore`.
- **Arbitrary Customer Toolchains (ADR-015):** when the repository needs binaries outside the optional presets (such as `nx` monorepo CLIs or custom internal tools), author or extend `.factory/Dockerfile.customer` directly on top of the digest-pinned pack base image and run `python3 core-gcp-fde/scripts/factory_onboard.py validate-dockerfile --dockerfile .factory/Dockerfile.customer`.
- Day-0 setup security checks (`validate-dockerfile`, untrusted workspace hooks, AI file divergence) run in **advisory mode by default** (flagging findings clearly in output and `.factory/modernization-backlog.yaml` with exit `0` so setup stays fluid; pass `--strict` only when a team explicitly requests blocking Day-0 checks). Runtime PR `security-auditor` remains strict.
- Adapt existing CI workflows non-destructively (keeping legacy jobs intact) and sync the overlay into the Hub project via `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply --kit <kit> --hub <url> --landing-zone <outputs.json> --repo <TARGET_REPO>`.
- source: https://cloud.google.com/architecture/framework/operational-excellence
