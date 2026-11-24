# ADR-010: Scion Hub Hardening and Pinned Supply Chain

- **Status:** Accepted
- **Date:** 2026-11-22
- **Invariants:** [INV-06](../INVARIANTS.md#inv-06-digest-pinned-runtime-and-harness-images), [INV-14](../INVARIANTS.md#inv-14-pinned-scion-release-and-fail-closed-hub-iam)

## Context

Floating upstream `main` references break reproducible deployments and introduce unverified supply-chain changes.
Default Scion Hub settings can allow broad GCP metadata access or silently skip IAM verification if not explicitly hardened.
HC-01 live verification proved three Scion `v0.4.0-preview.3` runtime requirements.
First, binding Lite Single-VM to `127.0.0.1` forces Docker host networking, which Scion refuses under GCP metadata mode `assign`.
Second, Policy Troubleshooter v3 requires `policytroubleshooter.googleapis.com` on `hub_project_id` and returns `UNKNOWN_INFO` for org-level deny policies when the Hub SA holds project-scoped `roles/iam.securityReviewer` only.
Third, Kubernetes runtime requires `https://` for in-cluster Hub endpoints, annotated Workload Identity KSAs, read-only `serviceaccounts` RBAC, persistent Hub DB storage, and RWX shared-dir storage.

## Decision

1. Pin the tested upstream Scion tag (`v0.4.0-preview.3`) and release tarball SHA-256 checksum in `compat.yaml` and `deploy/02-factory-runtime/lite-vm/variables.tf`.
2. Enable `policytroubleshooter.googleapis.com` on `hub_project_id` and enforce Hub IAM controls across both VM and GKE runtimes:
   - `default_gcp_identity_mode: "block"`
   - `default_agent_role: "baseline"`
   - `server.hub.gcp_iam_check_mode: "enforce"`
   - `server.hub.gcp_iam_deny_unknown_policy: "fail-open"` for project-scoped Hub SAs (override to `fail-closed` when org-level `roles/iam.denyReviewer` is granted).
3. Provision Lite Single-VM instances with Shielded VM enabled, OS Login enabled, zero public IP addresses (outbound via Cloud NAT, operator access via IAP SSH), Docker Artifact Registry credential helper on systemd PATH, `--host 0.0.0.0`, an HTTPS `SCION_SERVER_BASE_URL`, and `server.broker.container_hub_endpoint: "http://scion-hub.internal:8080"`.
4. Align `deploy/02-factory-runtime/ha-gke` to upstream `deploy/helm/scion-hub` (non-root `scion-hub-gke` image) with GKE DNS control-plane access, persistent Hub DB, RWX shared-dir storage, in-cluster HTTPS termination, annotated Workload Identity KSAs (excluding `sandbox_janitor`), and read-only `serviceaccounts` RBAC.
5. Set project-scope Vertex AI environment variables (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI=true`) during Stage 03 bootstrap so container-side harness provisioners receive valid `auth-candidates.json`.
6. Namespace all Scion templates, skills, and harness configs with `<pack_prefix>-` so multiple packs coexist safely on one Hub.

## Consequences

- Operators must hold `roles/iam.serviceAccountUser` on each assignable Service Account before assigning it to an agent.
- Agent containers without an explicit Service Account receive zero GCP credentials (`block` mode).
- Every installed Scion binary and container image is cryptographically verified before execution.

## Enforcement

- `compat.yaml`
- `deploy/02-factory-runtime/lite-vm/{vm.tf,cloud-init.tftpl,variables.tf}`
- `deploy/03-hub-bootstrap/bootstrap-hub-project.sh`
- `tests/test_terraform_and_scaffold_parity.py`
