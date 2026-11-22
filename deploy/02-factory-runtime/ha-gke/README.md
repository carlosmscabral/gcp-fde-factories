# Stage 02 — HA GKE Profile (`ha-gke`)

Use this profile for production customer deployments requiring multi-replica availability, Cloud SQL persistence, GCS storage, and IAP-protected HTTPS ingress.

## Design

- Delegates core GKE, Cloud SQL, and Scion Hub deployment to the official `GoogleCloudPlatform/scion/deploy/terraform` module pinned to the exact release tag in `compat.yaml` (`v0.4.0-preview.3`).
- Consumes the Stage 01 `landing-zone-outputs.json` contract (`hub_project_id`, `subnet_self_link`, `hub_sa_email`, `iap_proxy_sa_email`, `artifact_registry_url`).
- Enforces `default_gcp_identity_mode = "block"` in Stage 03 (`bootstrap-hub-project.sh`) so GKE agents never fall back to the Kubernetes runtime `passthrough` default.
