---
name: gcp-fde-guardrails
description: Core Google Cloud FDE factory guardrails overriding periodic sweeps, enforcing diversity profiles, and bounding agent execution.
---

# GCP FDE Factory Guardrails

## Rule 1 — Wake Only on External Delta Events or Weekly Kaizen
- Do not schedule frequent coordinator sweeps every 15 to 30 minutes.
- Wait for the external Delta Watcher (`scripts/delta-watcher`), the scheduled `daily-kaizen` message (`--wake`), or a human message to wake the coordinator.
- source: https://github.com/GoogleCloudPlatform/scion

## Rule 2 — Enforce Model Diversity at Spawn
- Read `diversity_profile` from `.factory/hub-project.yaml` before spawning `code-reviewer`.
- If `diversity_profile` is `cross-vendor`, spawn `developer` and `code-reviewer` on different model vendors.
- If `diversity_profile` is `cross-model`, spawn `developer` and `code-reviewer` on distinct models from the same vendor.
- If `diversity_profile` is `single-family`, record a mandatory human review warning in the PR description.
- source: https://github.com/scion-frontiers/agent-team

## Rule 3 — Never Auto-Merge to Main in v1
- Stop every workflow at a verified Pull Request with human approval required.
- Never invoke `gh pr merge` on protected branches in v1.
- source: https://github.com/scion-frontiers/agent-team

## Rule 4 — Enforce Least-Privilege SA Isolation
- Never spawn `developer`, `architect`, or `code-reviewer` with a Sandbox Deployer or Evaluator Service Account.
- Assign `<prefix>-deployer` (`gecx-deployer` or `adk-deployer`) only to `<prefix>-deployer`, and `<prefix>-evaluator` (`gecx-evaluator` or `adk-evaluator`) only to `<prefix>-eval-tester`.
- Never register DEV, HML, or PRD Service Accounts in the Scion Hub.
- source: https://cloud.google.com/iam/docs/best-practices-service-accounts

## Rule 5 — Respect Hard FinOps Bounds
- If the Inference Project budget guard revokes `roles/aiplatform.user`, halt all retries immediately and escalate to the customer operator.
- source: https://cloud.google.com/billing/docs/how-to/budgets-programmatic-notifications
