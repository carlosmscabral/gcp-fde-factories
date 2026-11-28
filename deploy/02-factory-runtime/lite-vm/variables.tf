# Input variables for Stage 02 (Factory Runtime — Lite Single-VM).
# Consumes outputs exported by Stage 01 (01-landing-zone).

variable "hub_project_id" {
  description = "Google Cloud project ID hosting the Scion Hub VM."
  type        = string
}

variable "region" {
  description = "Region for the Scion Hub subnet."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for the Lite Single-VM Scion Hub."
  type        = string
  default     = "us-central1-a"
}

variable "name_prefix" {
  description = "Prefix matching Stage 01 network tags and service accounts."
  type        = string
  default     = "gecx-factory"
}

variable "subnet_self_link" {
  description = "Self link of the non-default custom or Shared VPC subnet from Stage 01."
  type        = string
}

variable "hub_sa_email" {
  description = "Service account email for the Scion Hub VM from Stage 01."
  type        = string
}

variable "artifact_registry_url" {
  description = "Artifact Registry repository URL from Stage 01."
  type        = string
}

variable "machine_type" {
  description = "GCE machine type for the Lite Single-VM Scion Hub."
  type        = string
  default     = "e2-standard-8"
}

variable "scion_version" {
  description = "Pinned Scion release tag matching compat.yaml (never floating latest)."
  type        = string
  default     = "v0.4.0-preview.4"
}

variable "scion_binary_sha256" {
  description = "Pinned SHA-256 hex digest of scion-linux-amd64.tar.gz matching compat.yaml (verified offline before extraction)."
  type        = string
  default     = "0eaac10191dd948906c0957c78fdfd96eeef0a6e7cc56e3e30d2d728144ca5b9"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.scion_binary_sha256))
    error_message = "scion_binary_sha256 must be a 64-character lowercase SHA-256 hex digest."
  }
}

variable "hub_public_url" {
  description = "Optional HTTPS public URL when behind an IAP Cloud Run proxy. Leave empty to use an internal HTTPS base URL with bridge-mode container_hub_endpoint."
  type        = string
  default     = ""

  validation {
    condition     = var.hub_public_url == "" || startswith(var.hub_public_url, "https://")
    error_message = "hub_public_url must be empty or start with https://."
  }
}

variable "gcp_iam_deny_unknown_policy" {
  description = "Policy Troubleshooter fallback when Allow is GRANTED but org-level Deny is UNKNOWN (fail-open recommended for project-scoped Hub SAs; fail-closed requires org roles/iam.denyReviewer)."
  type        = string
  default     = "fail-open"

  validation {
    condition     = contains(["fail-open", "fail-closed"], var.gcp_iam_deny_unknown_policy)
    error_message = "gcp_iam_deny_unknown_policy must be fail-open or fail-closed."
  }
}

variable "admin_emails" {
  description = "Optional list of Google Workspace or Cloud Identity emails granted Scion Hub admin access."
  type        = list(string)
  default     = []
}

variable "oidc_allowed_domains" {
  description = "Optional list of allowed Google OIDC domains for headless gcloud identity-token authentication over IAP SSH."
  type        = list(string)
  default     = []
}

variable "oidc_allowed_gcp_projects" {
  description = "Optional list of GCP project IDs allowed to authenticate via Google Service Account OIDC identity tokens."
  type        = list(string)
  default     = []
}

variable "boot_image" {
  description = "OS image for the Hub VM boot disk. Override with a customer corporate golden image when compute.trustedImageProjects is enforced."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2204-lts"
}

variable "boot_disk_kms_key_self_link" {
  description = "Optional Cloud KMS key self_link for CMEK boot disk encryption when gcp.restrictNonCmekServices is enforced."
  type        = string
  default     = null
}
