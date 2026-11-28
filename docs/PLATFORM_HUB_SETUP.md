# Platform and Hub Setup Guide (`1 Hub → N Factories`)

This guide separates one-time platform infrastructure setup (**Phase A**) from repeatable per-repository factory onboarding (**Phase B**).

## 1. Architecture Boundary

| Phase | Cadence | Owner | Artifacts and Actions |
| :--- | :--- | :--- | :--- |
| **Phase A: Platform / Hub Setup** | **1×** per organization or environment | Platform / Cloud Engineer | Stage 01 GCP Landing Zone, Stage 02 Scion Hub (`lite-vm` or `ha-gke`), Hub-wide GitHub App, `hub.admin_managed_brokers`, Hub defaults |
| **Phase B: Factory Onboarding** | **N×** per repository or monorepo subproject | Product Owner + Tech Lead | Tier-A `scan`, 2-block `/grill-me`, `.factory/[<prefix>/]factory.yaml`, optional `Dockerfile.customer`, `validate`, `emit --pr`, Stage 03 `apply` |

NOTE: One Scion Hub safely hosts multiple factories across distinct repositories and distinct monorepo subprojects.

## 2. Phase A — Platform / Hub Setup (Run Once)

1. Apply Stage 01 Terraform (`deploy/01-landing-zone`) to create the Hub VPC, Artifact Registry, Staging bucket, and least-privilege Service Accounts.
   - Set `enable_sandbox_project = false` when onboarded repositories use `ci-only` or `deploy_target: none`.
   - Set `enable_delta_watcher = true` if you want zero-token GitHub Issue polling behind IAP.
2. Apply Stage 02 Terraform (`deploy/02-factory-runtime/lite-vm` or `deploy/02-factory-runtime/ha-gke`) to boot Scion Hub `v0.4.0-preview.4`.
3. Configure Hub-global Git authentication once in the Hub Admin UI (`/admin/server-config -> GitHub App`).
   - Recommended (enterprise): Scion GitHub App mints short-lived 1-hour repository-scoped tokens with zero PAT rotation.
   - Fallback (PAT or non-GitHub HTTPS host such as GitLab/ADO): store a project-scoped `GITHUB_TOKEN` secret with `injectionMode=always`.
4. Lock Hub-wide governance, lifecycle, and telemetry defaults **once** using Phase A `platform-init`:
   ```bash
   <kit>/bootstrap/bootstrap-hub-project.sh platform-init \
     --kit <kit> \
     --hub <HUB_URL> \
     --landing-zone <lz-outputs.json>
   ```
   - Sets `gcp_iam_check_mode=enforce`, `default_gcp_identity_mode=block`, Hub-global limits, `lifecycle.idle_suspend`, `lifecycle.never_suspend`, Decisions/Artifacts experiments, `hub.admin_managed_brokers`, and GCP telemetry once.
   - Set `ENFORCE_ADMIN_MANAGED_BROKERS=true` on dedicated Hubs to block unmanaged developer laptops from registering as brokers.
   - Subsequent factories attaching with `existing_hub: true` never overwrite these Hub-global settings.
5. Stage the desired Factory Pack Release Kit (`stage-release-kit.sh --mode rebuild`) into your Hub Artifact Registry so `@sha256` digests are immutable.

## 3. Phase B — Per-Factory Onboarding (Repeat N× on the Same Hub)

1. Run the zero-dependency `<2s` Tier-A scan on the target repository:
   ```bash
   python3 core-gcp-fde/scripts/factory_onboard.py scan \
     --repo /path/to/repo \
     --pack generic \
     --roster-preset lean \
     --emit-draft /tmp/factory-draft.yaml
   ```
2. Complete the 2-block `/grill-me` interview (4 PO questions + 4 Engineering questions pre-filled from real CI workflows).
   - Set `confirmed_by` to the human approver's name.
   - Choose `roster.preset: lean` (default 5 roles: fastest setup, lowest token cost) or `roster.preset: full` (full `agent-team` hierarchy for complex multi-stream repositories; can be upgraded on Day 2).
   - In monorepos with multiple factories, set `monorepo.enabled: true`, `monorepo.subdir`, and a unique `monorepo.agent_prefix`. Config emits to `.factory/<prefix>/factory.yaml` without colliding with sibling factories.
3. If the repository requires runtimes outside the pack base image, author `.factory/[<prefix>/]Dockerfile.customer` inheriting `ARG BASE_IMAGE` and list every required command in `toolchain.verify_binaries`.
4. Preview diffs (`emit --dry-run`), open the onboarding PR (`emit --pr`), and verify with one fail-closed command:
   ```bash
   python3 core-gcp-fde/scripts/factory_onboard.py validate \
     --repo /path/to/repo \
     [--config .factory/<prefix>/factory.yaml]
   ```
5. Merge the onboarding PR into `origin/<base_branch>`.
6. Link the repository to the Hub (`scion hub link`) and reconcile Stage 03:
   ```bash
   <kit>/bootstrap/bootstrap-hub-project.sh apply \
     --kit <kit> \
     --hub <HUB_URL> \
     --landing-zone <lz-outputs.json> \
     --repo /path/to/repo \
     [--config .factory/<prefix>/factory.yaml]
   ```
   - Stage 03 lints `.factory/[<prefix>/]Dockerfile.customer` (and optional `Dockerfile.tester`), archives only committed files from `origin/<base_branch>`, builds via the isolated Sandbox Cloud Build SA (`sandbox_builder` -> `sandbox_images` AR when `enable_sandbox_project = true`), verifies every `toolchain.verify_binaries` command as non-root `scion` inside `docker build --network=none`, and pins the resulting `@sha256` digest into a factory-isolated harness-config.
   - On 2-project Hubs (`enable_sandbox_project = false`), building a custom customer Dockerfile into Hub Artifact Registry fails closed unless the operator explicitly passes `--allow-hub-customer-image-build`.

## 4. Honest Boundaries (`best_effort` and Tier-C Escape Hatch)

- **GitHub.com and GHES (`native_github`):** Full support for Scion GitHub App, `gh` PR creation, GitHub Actions WIF Verdict Gates, and External Delta Watcher.
- **GitLab, Azure DevOps, Bitbucket (`best_effort`):** HTTPS clone/push works via Scion's project-scoped `GITHUB_TOKEN` secret. PR automation and Delta Watcher polling are not native; keep `intake.enabled: false` and trigger runs via Scion Web Chat or CLI.
- **Tier-C Build Systems (Bazel, Nix flakes, Xcode, CUDA/GPU, external Jenkins `@Library`):** Detected early during Tier-A scan. Supply an explicit custom `.factory/Dockerfile.customer` or select `mode: ci-only` instead of relying on automatic container heuristics.
