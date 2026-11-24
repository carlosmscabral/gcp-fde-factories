# ADR-002: Three-Stage Deployment and Project Topologies

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-02](../INVARIANTS.md#inv-02-additive-iam-and-explicit-stage-contracts)

## Context

Enterprise cloud security teams control IAM, networking, and budgets in separate organizations from application engineering teams.
A monolithic Terraform root mixes Landing Zone governance with runtime deployment and Hub configuration.
Customers also vary in project availability: production deployments use three projects, while pilots use two or one project.

## Decision

1. Split infrastructure delivery into three decoupled stages under `deploy/`.
   - **Stage 01 (`deploy/01-landing-zone`):** APIs, optional custom VPC and Cloud NAT, Artifact Registry, FinOps budget alerts, custom IAM roles, and Service Accounts.
   - **Stage 02 (`deploy/02-factory-runtime`):** Scion Hub runtime (`lite-vm` for pilots or `ha-gke` for production).
   - **Stage 03 (`deploy/03-hub-bootstrap`):** Image staging (`deploy/03-hub-bootstrap/stage-release-kit.sh`) and idempotent Hub configuration (`deploy/03-hub-bootstrap/bootstrap-hub-project.sh`).
2. Pass data between stages through explicit JSON outputs (`landing-zone-outputs.json`), never through implicit `terraform_remote_state` coupling.
3. Accept three independent project variables (`hub_project_id`, `inference_project_id`, `sandbox_project_id`) and deduplicate API and IAM targets automatically.
4. Use additive IAM resources (`google_project_iam_member`, `google_service_account_iam_member`, `google_storage_bucket_iam_member`) exclusively.

## Consequences

- Security teams review and apply Stage 01 once, then hand `landing-zone-outputs.json` to delivery engineers.
- The same Terraform codebase supports 3-project, 2-project, and 1-project topologies with zero code forks.
- Additive IAM prevents Terraform from overwriting existing customer project bindings.

## Enforcement

- `deploy/01-landing-zone/{apis,iam,network,finops,outputs}.tf`
- `deploy/02-factory-runtime/{lite-vm,ha-gke}/`
- `deploy/03-hub-bootstrap/{stage-release-kit.sh,bootstrap-hub-project.sh}`
- `tests/test_terraform_and_scaffold_parity.py`
