---
name: generic-software-guardrails
description: Operational guardrails for packs/generic (sw-*) factories covering Knowledge Plane traceability, brownfield container adaptation, non-GitHub Wave-1 queues, and honest L1/L2 verification.
---

# Generic Software Guardrails (`packs/generic`)

## 1. Knowledge Plane and Brownfield Boundaries
- Read `.factory/factory-profile.yaml`, `.factory/knowledge-index.yaml`, `.factory/knowledge/requirements.md`, and `.factory/knowledge/invariants.md` before starting implementation or review.
- Keep pre-existing repository AI files (`CLAUDE.md`, `GEMINI.md`, `.cursorrules`) and legacy CI jobs intact without destructive rewrites.
- When `monorepo.enabled` is true in `.factory/hub-project.yaml`, restrict code changes, tests, and builds to `monorepo.subdir` unless a cross-package contract explicitly requires shared edits.
- Run `python3 /opt/gcp-fde/factory_onboard.py kp-check --repo .` whenever documentation, requirements, invariants, or `.factory/waves/wave-1.yaml` change.
- source: https://github.com/scion-frontiers/agent-team

## 2. Container Toolchain and Deploy Target Discipline
- Add repository-specific language runtimes (Node, pnpm, Go, Rust, Java, Nx, Playwright) strictly through `.factory/Dockerfile.customer` or `.factory/Dockerfile.customer-tester` layered on the digest-pinned `generic-runtime` image.
- Validate custom Dockerfiles with `python3 /opt/gcp-fde/factory_onboard.py validate-dockerfile --dockerfile .factory/Dockerfile.customer`.
- Respect `deploy_target` in `.factory/hub-project.yaml`:
  - When `deploy_target` is `none` (library, CLI, or static package), never invoke cloud deploy commands or spawn `sw-generic-deployer`.
  - When `deploy_target` is `cloud-run`, `gke`, or `custom` under `sandbox-direct`, route all Sandbox deployments strictly to `sw-generic-deployer` with `[CI]` ephemeral naming.
- source: https://cloud.google.com/architecture/framework/operational-excellence

## 3. Work Queue Portability and Honest L1/L2 Verification
- When `git_flow.ci_platform` is `github-actions`, sync Wave-1 items with GitHub Issues and PRs.
- When `git_flow.ci_platform` is `azure-devops`, `gitlab-ci`, or `none`, treat `.factory/waves/wave-1.yaml` as the seed queue, track live worker state via Scion notifications and `/scion-volumes/scratchpad/wave-state.jsonl`, and update `wave-1.yaml` only from the Coordinator via a dedicated PR.
- Run `python3 /opt/generic-factory/generic_sandbox_gate.py --level 1` on every PR before review. Run `--level 2` when `deploy_target` differs from `none` (fails closed if `commands.e2e` is empty).
- Never claim sandbox verification for items listed in `not_verifiable_in_sandbox`. Flag them explicitly in the PR summary for human verification.
- source: https://github.com/GoogleCloudPlatform/scion
