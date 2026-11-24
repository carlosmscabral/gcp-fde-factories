---
name: factory-onboard
description: Day-0 brownfield onboarding skill (scion-defaults-inspired) combining 0-token repo scanning, 2-track PO /grill-me interview, Readiness Gate, and pure Layer 3 .factory/ overlay generation.
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
- Offer two tracks:
  - **Express (~10 min):** confirm scanner facts, choose `mode` (`sandbox-direct` or `ci-only`), `diversity_profile`, `autonomy`, limits, Kaizen schedule (`America/Sao_Paulo`), index existing docs/ADRs in-place, and capture brownfield gaps in `modernization-backlog.yaml`.
  - **Complete (~25 min):** cover all Express topics plus guided `mission`, `non_goals`, testable `REQ-NNN` requirements, verifiable `invariants`, and `evaluation_pyramid` targets.
- source: https://github.com/scion-frontiers/agent-team

## 3. Pass the Readiness Gate and Emit Pure Layer 3 Overlay
- Save the confirmed answers to a profile YAML and run `python3 core-gcp-fde/scripts/factory_onboard.py check --profile <profile.yaml>`.
- Repeat until `"ready": true`. Never emit overlay files while `missing_or_weak` is non-empty.
- Run `python3 core-gcp-fde/scripts/factory_onboard.py emit --repo <TARGET_REPO> --profile <profile.yaml> --pack-image <PACK_IMAGE_DIGEST>`.
- Confirm zero existing customer files (`CLAUDE.md`, `.cursorrules`, CI workflows) were overwritten, `AGENTS.md` only gained the delimited factory block, and `.factory/Dockerfile.customer` was created only if `missing_binaries` was non-empty.
- Sync the overlay into the target Hub project with `deploy/03-hub-bootstrap/bootstrap-hub-project.sh apply --kit <kit> --hub <url> --repo <TARGET_REPO>`.
- source: https://cloud.google.com/architecture/framework/operational-excellence
