# Stage 02 — HA GKE Runtime Contract Bridge (`ha-gke`)

> **Status: Validated Contract Bridge (HC-01 Verified).** This module validates Stage 01 outputs and emits the normalized parameter and security contract (`normalized_runtime_contract`) for deploying upstream `GoogleCloudPlatform/scion` (`v0.4.0-preview.3`) on GKE.

## Upstream References (Verified in HC-01)

- **Helm Chart:** `https://github.com/GoogleCloudPlatform/scion/tree/v0.4.0-preview.3/deploy/helm/scion-hub`
- **Terraform Stack:** `git::https://github.com/GoogleCloudPlatform/scion.git//deploy/terraform/configurations/hub-gke?ref=v0.4.0-preview.3`
- **Hub GKE Image Spec:** `https://github.com/GoogleCloudPlatform/scion/blob/v0.4.0-preview.3/image-build/cloudbuild-hub-gke.yaml`

## Mandatory GKE Runtime Contracts (HC-01 and HC-02 Verified)

1. **Private-Nodes Control Plane Access (HC-01 F9):** Enable GKE DNS endpoint access (`--enable-dns-access`) or explicit Master Authorized Networks so IAM-authenticated operators can manage the cluster.
2. **Dedicated Least-Privilege GKE Node SA (HC-02 F4):** Set `enable_gke_api = true` in Stage 01 and pass `--service-account=<gke_node_sa_email>` (`roles/container.defaultNodeServiceAccount` + `roles/artifactregistry.reader` on `hub_project_id`) when creating the cluster so hardened projects without Compute Default SA `roles/editor` do not hit `403 ImagePullBackOff`.
3. **Custom-VPC Filestore CSI StorageClass (HC-01 F20, HC-02 F7):** GKE's built-in `standard-rwx` hardcodes `network: default` and fails when `constraints/compute.skipDefaultNetworkCreation` is active. Create a custom `StorageClass` (`filestore.csi.storage.gke.io`) setting `parameters.network: <vpc_name>` (from Stage 01 output `vpc_name`) and `volumeBindingMode: Immediate` so the RWX share binds before the first agent launch.
4. **Cloud Build GKE Hub Logs Bucket (HC-02 F2):** Upstream `image-build/cloudbuild-hub-gke.yaml` omits `options.logging: CLOUD_LOGGING_ONLY`. Pass `--gcs-log-dir=gs://<sandbox_staging_bucket>/cloudbuild-logs` when building under `release_builder_sa_email`.
5. **Workload Identity KSAs + RBAC (HC-01 F18):** Create annotated Kubernetes ServiceAccounts (`iam.gke.io/gcp-service-account`) in namespace `scion` for `factory-worker`, `pack-deployer`, and `pack-evaluator` only (never `sandbox-janitor`), bind `roles/iam.workloadIdentityUser`, and grant the `scion-hub` K8s Role `get/list/watch` on `serviceaccounts`.
6. **In-Cluster HTTPS Hub Endpoint (HC-01 F22):** Expose `scion-hub` over internal HTTPS (`hub_transport_policy` rejects `http://` endpoints on Kubernetes runtimes).
7. **Persistent Hub Database (HC-01 F25, HC-02 M5.4):** Override the Helm chart default `emptyDir` SQLite mount with a `ReadWriteOnce` PersistentVolumeClaim (`scion-hub-home`) or Cloud SQL Postgres so Hub pod restarts preserve projects, secrets, templates, schedules, and RoleBindings with zero state loss.
8. **Fail-Closed Identity Defaults:** Keep `default_gcp_identity_mode=block`, `default_agent_role=baseline`, `gcp_iam_check_mode=enforce`, and `gcp_iam_deny_unknown_policy=fail-open` for project-scoped Hub SAs.

See [deploy/ENTERPRISE_PREREQUISITES.md](../../ENTERPRISE_PREREQUISITES.md) for the complete customer Org Policy and administrative checklist.
