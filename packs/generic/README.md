# `packs/generic` (`sw-*`, `v0.6.0` `contrafile`)

Generic software engineering Factory Pack built on `scion-frontiers/agent-team` (SEP) and `core-gcp-fde-base` for arbitrary brownfield or greenfield software repositories (Go, Node/TypeScript, Python, Java, Rust, frontend web apps, APIs, CLIs, libraries, or monorepos).

## Included Components
- **15 Offline Templates (`sw-*`):** All 13 upstream `agent-team` SEP roles plus `sw-generic-deployer` and `sw-kaizen-analyst`, within the `<= 1,800` line context budget.
- **10 Hub Skill Bank Skills:** 4 project-attached (`gcp-fde-guardrails`, `gcp-sandbox-contract`, `gcp-kaizen-light`, `generic-software-guardrails`) and 6 role-scoped (`software-engineering-process`, `agent-state-continuity`, `artifact-durability`, `code-review`, `release-notes-daily`, `gcp-kaizen-analyst`).
- **Lean Runtime Base (`packs/generic/Dockerfile`):** Extends `core-gcp-fde-base` without ADK or CES dependencies. Customer repositories add language toolchains through `.factory/Dockerfile.customer` and `.factory/Dockerfile.customer-tester` (ADR-015).
- **Profile-Driven Gate and Janitor (`scripts/generic_sandbox_gate.py`, `scripts/sandbox_janitor.py`):** Runs scrubbed Level 1 offline checks (`build`, `lint`, `test`, optional `--base-ref`), Level 2 sandbox checks (`e2e`, failing closed when `deploy_target != none` and `e2e` is empty), and sweeps expired `[CI]` / `factory_ci=true` Cloud Run services.
- **Landing Zone Flexibility (`deploy/01-landing-zone/`):** Supports narrow Cloud Run Sandbox custom roles (`enable_generic_sandbox_roles = true`), or exceptional 2-project / 1-project CI-only topologies without a Sandbox project (`enable_sandbox_project = false`, `deploy_target: none`). For `gke` or `custom` deploy targets, supply custom Sandbox IAM or use `mode: ci-only`.

## Quickstart
```bash
./build.sh --check packs/generic
./build.sh --release-kit packs/generic --out /tmp/generic-kit
.venv/bin/python core-gcp-fde/scripts/factory_onboard.py scan --repo /path/to/repo --pack generic --emit-draft /tmp/profile-draft.yaml
```
