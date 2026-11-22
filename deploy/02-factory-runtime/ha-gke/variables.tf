# Input variables for Stage 02 HA GKE profile.
# Maps Stage 01 landing-zone outputs onto the upstream Scion GKE Terraform deployment contract.

variable "hub_project_id" {
  description = "Google Cloud project ID hosting the HA GKE Scion Hub."
  type        = string
}

variable "region" {
  description = "Google Cloud region for the GKE cluster and Cloud SQL instance."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix matching Stage 01 networking and service accounts."
  type        = string
  default     = "gecx-factory"
}

variable "subnet_self_link" {
  description = "Non-default custom or Shared VPC subnet self link from Stage 01."
  type        = string
}

variable "hub_sa_email" {
  description = "Scion Hub runtime Service Account email from Stage 01."
  type        = string
}

variable "iap_proxy_sa_email" {
  description = "Zero-role Cloud Run IAP proxy Service Account email from Stage 01."
  type        = string
}

variable "artifact_registry_url" {
  description = "Artifact Registry URL from Stage 01."
  type        = string
}

variable "scion_version" {
  description = "Pinned Scion release tag matching compat.yaml."
  type        = string
  default     = "v0.4.0-preview.3"
}

variable "iap_domain" {
  description = "Internal customer HTTPS domain fronted by IAP."
  type        = string
}
