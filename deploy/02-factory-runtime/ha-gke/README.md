# Stage 02 — HA GKE Runtime Contract Bridge (`ha-gke`)

> **Status: Validated Contract Bridge (HC-01 Verified).** This module validates Stage 01 outputs and emits the normalized parameter and security contract (`normalized_runtime_contract`) for deploying upstream `GoogleCloudPlatform/scion` (`v0.4.0-preview.3`) on GKE.

## Upstream References (Verified in HC-01)

- **Helm Chart:** `https://github.com/GoogleCloudPlatform/scion/tree/v0.4.0-preview.3/deploy/helm/scion-hub`
- **Terraform Stack:** `git::https://github.com/GoogleCloudPlatform/scion.git//deploy/terraform/configurations/hub-gke?ref=v0.4.0-preview.3`
- **Hub GKE Image Spec:** `https://github.com/GoogleCloudPlatform/scion/blob/v0.4.0-preview.3/image-build/cloudbuild-hub-gke.yaml`

## Mandatory GKE Runtime Contracts (HC-01 F9, F18, F20, F22, F25)

1. **Private-Nodes Control Plane Access (F9):** Enable GKE DNS endpoint access (`--enable-dns-access`) or explicit Master Authorized Networks so IAM-authenticated operators can manage the cluster.
2. **Workload Identity KSAs + RBAC (F18):** Create annotated Kubernetes ServiceAccounts (`iam.gke.io/gcp-service-account`) in namespace `scion` for `factory-worker`, `pack-deployer`, and `pack-evaluator` only (never `sandbox-janitor`), bind `roles/iam.workloadIdentityUser`, and grant the `scion-hub` K8s Role `get/list/watch` on `serviceaccounts`.
3. **RWX Shared-Dir Storage (F20):** Configure a `ReadWriteMany` storage class (for example, GKE Filestore CSI `standard-rwx` or NFS) for project shared directories (`scratchpad`).
4. **In-Cluster HTTPS Hub Endpoint (F22):** Expose `scion-hub` over internal HTTPS (`hub_transport_policy` rejects `http://` endpoints on Kubernetes runtimes).
5. **Persistent Hub Database (F25):** Override the Helm chart default `emptyDir` SQLite mount with a PersistentVolumeClaim or Cloud SQL Postgres so Hub pod restarts preserve projects, secrets, templates, schedules, and RoleBindings.
6. **Fail-Closed Identity Defaults:** Keep `default_gcp_identity_mode=block`, `default_agent_role=baseline`, `gcp_iam_check_mode=enforce`, and `gcp_iam_deny_unknown_policy=fail-open` for project-scoped Hub SAs.
