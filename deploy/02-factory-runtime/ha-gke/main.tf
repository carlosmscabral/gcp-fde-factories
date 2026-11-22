# Stage 02 HA GKE contract bridge for official GoogleCloudPlatform/scion/deploy/terraform.
# Validates Stage 01 inputs and exposes normalized parameters for the upstream pinned module.
# Operators uncomment the module block below when deploying the HA GKE tier into customer production.

locals {
  upstream_scion_module_source = "git::https://github.com/GoogleCloudPlatform/scion.git//deploy/terraform?ref=${var.scion_version}"

  scion_ha_gke_inputs = {
    project_id             = var.hub_project_id
    region                 = var.region
    name_prefix            = var.name_prefix
    subnet_self_link       = var.subnet_self_link
    hub_service_account    = var.hub_sa_email
    iap_service_account    = var.iap_proxy_sa_email
    image_registry         = var.artifact_registry_url
    public_url             = "https://${var.iap_domain}"
    gcp_iam_check_mode     = "enforce"
    gcp_iam_deny_unknown   = "fail-closed"
    default_identity_mode  = "block"
  }
}

# Example upstream delegation block (pinned to compat.yaml tag, never floating main):
# module "scion_hub_ha" {
#   source = "git::https://github.com/GoogleCloudPlatform/scion.git//deploy/terraform?ref=v0.4.0-preview.3"
#   ...
# }

output "upstream_module_ref" {
  description = "Pinned upstream Scion Terraform module reference."
  value       = local.upstream_scion_module_source
}

output "normalized_runtime_contract" {
  description = "Validated Stage 01 -> Stage 02 HA GKE parameter bundle."
  value       = local.scion_ha_gke_inputs
}
