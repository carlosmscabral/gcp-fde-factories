---
name: factory-onboard
description: Day-0 brownfield onboarding skill (scion-defaults-inspired) combining 0-token repo scanning, 2-track PO /grill-me interview (including Vertex AI harness/model tuning), Readiness Gate, and pure Layer 3 .factory/ overlay generation.
---

# Factory Onboard (`v0.4.0`)

## 1. Detect Existing vs. New Hub and Scan Statically First
- Ask the human whether this repository targets a **New Scion Hub** (run Stages 01, 02, and 03) or an **Existing Scion Hub** (2nd+ factory on the same Hub: skip Stages 01 and 02 and run Stage 03 `apply --repo` on a new Hub project).
- Run `python3 core-gcp-fde/scripts/factory_onboard.py scan --repo <TARGET_REPO> --toolchain-manifest packs/<pack>/toolchain-manifest.json` before asking any technical question.
- Present detected facts (stack, commands, `missing_binaries`, pre-existing AI files, Git Flow, CI workflows, and knowledge sources) in a short table and ask the PO to confirm or correct them.
- source: https://github.com/GoogleCloudPlatform/scion

## 2. Conduct the 2-Track PO Interview (`/grill-me`) One Topic at a Time
- Never ask static facts already detected by the scanner. Never invent business intent, SLOs, autonomy rules, or acceptance criteria without explicit PO confirmation.
- Challenge vague answers until every requirement or invariant is verifiable by a diff or command.
- **Vertex AI Harnesses & Models (opinionated Vertex AI default — customer may change auth later in Scion):**
  - Use Scion's generic semantic tier aliases (`small`, `medium`, `large`, `extra-large`) and `thinking_level` (`0–100`) instead of hardcoded model versions so concrete models evolve automatically with upstream Scion releases (explicit model IDs remain supported as per-role overrides).
  - Ask whether Anthropic **Claude** was manually enabled in **Vertex AI Model Garden** on `inference_project_id`, and whether `global` endpoints are allowed (or regional residency `us`/`eu`/`us-east5` is required).
  - If **enabled**: propose `diversity_profile: cross-vendor` with `harnesses.claude_model_garden_enabled: true`. Assign `developer` and `architect` to `antigravity-vertex` tier `extra-large` (thinking `100`), `code-reviewer` and `security-auditor` to `claude-vertex` tier `large` (thinking `75`), and `doc-writer` to tier `medium`.
  - If **not enabled** (1P Gemini only): propose `diversity_profile: cross-model` with `harnesses.claude_model_garden_enabled: false`. Assign `developer` and `architect` to `antigravity-vertex` tier `extra-large` (thinking `100`), and `code-reviewer` and `security-auditor` to `antigravity-vertex` tier `large` (or an explicit alternate Gemini model ID) with thinking `100`.
  - Let the PO accept the preset or tune per-role `model_routing` entries (`harness`, `model`, `thinking_level`).
- Offer two tracks:
  - **Express (~10 min):** confirm scanner facts, choose `mode` (`sandbox-direct` or `ci-only`), Vertex AI harnesses/models, `autonomy`, limits, Kaizen schedule (`America/Sao_Paulo`, enabled by default), index existing docs/ADRs in-place, and capture brownfield gaps in `modernization-backlog.yaml`.
  - **Complete (~25 min):** cover all Express topics plus guided `mission`, `non_goals`, testable `REQ-NNN` requirements, verifiable `invariants`, and `evaluation_pyramid` targets.
- source: https://github.com/scion-frontiers/agent-team

## 3. Pass the Readiness Gate and Emit Pure Layer 3 Overlay
- Save the confirmed answers to a profile YAML and run `python3 core-gcp-fde/scripts/factory_onboard.py check --profile <profile.yaml>`.
- Repeat until `"ready": true`. Never emit overlay files while `missing_or_weak` is non-empty.
- Run `python3 core-gcp-fde/scripts/factory_onboard.py emit --repo <TARGET_REPO> --profile <profile.yaml> --pack-image <PACK_IMAGE_DIGEST>`.
- Confirm zero existing customer files (`CLAUDE.md`, `.cursorrules`, CI workflows) were overwritten, `AGENTS.md` only gained the delimited factory block, and `.factory/Dockerfile.customer` was created only if `missing_binaries` was non-empty.
- Sync the overlay into the target Hub project with `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply --kit <kit> --hub <url> --landing-zone <outputs.json> --repo <TARGET_REPO>`.
- source: https://cloud.google.com/architecture/framework/operational-excellence
