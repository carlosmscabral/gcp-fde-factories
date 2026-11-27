# Stage 02 HA GKE contract bridge for official GoogleCloudPlatform/scion Helm and Terraform stacks.
# HC-01 live verification (F1/F9/F18/F20/F22/F25) confirmed upstream v0.4.0-preview.3 ships:
#   - Helm chart: deploy/helm/scion-hub (non-root hub-gke image from image-build/cloudbuild-hub-gke.yaml)
#   - Terraform configurations: deploy/terraform/configurations/{shared-infra,hub-gke}
# Validates Stage 01 inputs and emits the normalized GKE runtime contract for operator deployment.

locals {
  upstream_scion_helm_chart_ref     = "https://github.com/GoogleCloudPlatform/scion/tree/${var.scion_version}/deploy/helm/scion-hub"
  upstream_scion_terraform_hub_ref  = "git::https://github.com/GoogleCloudPlatform/scion.git//deploy/terraform/configurations/hub-gke?ref=${var.scion_version}"
  upstream_scion_hub_gke_build_spec = "https://github.com/GoogleCloudPlatform/scion/blob/${var.scion_version}/image-build/cloudbuild-hub-gke.yaml"

  scion_ha_gke_inputs = {
    project_id                  = var.hub_project_id
    region                      = var.region
    name_prefix                 = var.name_prefix
    subnet_self_link            = var.subnet_self_link
    hub_service_account         = var.hub_sa_email
    iap_service_account         = var.iap_proxy_sa_email
    image_registry              = var.artifact_registry_url
    public_url                  = "https://${var.iap_domain}"
    gcp_iam_check_mode          = "enforce"
    gcp_iam_deny_unknown        = "fail-open"
    default_identity_mode       = "block"
    default_agent_role          = "baseline"
    telemetry_enabled           = true
    telemetry_cloud_provider    = "gcp"
    telemetry_gcp_project_id    = var.hub_project_id
    gke_dns_control_plane       = true
    hub_db_persistence          = "pvc-or-cloudsql-required"
    shared_dir_storage_class    = "standard-rwx"
    in_cluster_hub_tls_required = true
    agent_namespace             = "scion"
    required_k8s_rbac           = ["serviceaccounts:get,list,watch"]
    workload_identity_ksas = [
      "factory-coordinator",
      "factory-worker",
      "pack-deployer",
      "pack-evaluator",
    ]
    optional_workload_identity_ksas = [
      "kaizen-viewer",
    ]
    forbidden_workload_identity_ksas = [
      "sandbox-janitor",
    ]
  }
}

output "upstream_helm_chart_ref" {
  description = "Pinned upstream Scion Helm chart reference for GKE Hub deployment."
  value       = local.upstream_scion_helm_chart_ref
}

output "upstream_module_ref" {
  description = "Pinned upstream Scion Terraform hub-gke configuration reference."
  value       = local.upstream_scion_terraform_hub_ref
}

output "upstream_hub_gke_build_spec" {
  description = "Pinned upstream Cloud Build spec that builds the non-root scion-hub-gke container image."
  value       = local.upstream_scion_hub_gke_build_spec
}

output "normalized_runtime_contract" {
  description = "Validated Stage 01 -> Stage 02 HA GKE parameter and security contract bundle."
  value       = local.scion_ha_gke_inputs
}
