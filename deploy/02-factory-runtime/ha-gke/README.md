# Stage 02 — HA GKE Parameter Contract Bridge (Preview) (`ha-gke`)

> **Status: Preview Contract Bridge.** This module validates Stage 01 outputs and emits the normalized parameter map (`normalized_runtime_contract`) for the official upstream `GoogleCloudPlatform/scion/deploy/terraform` module. It does **not** provision GKE clusters or Cloud SQL directly until the operator uncomments and wires the pinned upstream `module "scion_hub_ha"` block.

Use this profile as the contract bridge for production customer deployments requiring multi-replica availability, Cloud SQL persistence, GCS storage, and IAP-protected HTTPS ingress.

## Design

- Delegates core GKE, Cloud SQL, and Scion Hub deployment to the official `GoogleCloudPlatform/scion/deploy/terraform` module pinned to the exact release tag in `compat.yaml` (`v0.4.0-preview.3`).
- Consumes the Stage 01 `landing-zone-outputs.json` contract (`hub_project_id`, `subnet_self_link`, `hub_sa_email`, `iap_proxy_sa_email`, `artifact_registry_url`).
- Enforces `default_gcp_identity_mode = "block"` in Stage 03 (`bootstrap-hub-project.sh`) so GKE agents never fall back to the Kubernetes runtime `passthrough` default.
