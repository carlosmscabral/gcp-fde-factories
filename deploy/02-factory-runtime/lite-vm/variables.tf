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
  default     = "v0.4.0-preview.3"
}

variable "hub_public_url" {
  description = "Optional HTTPS public URL when behind an IAP Cloud Run proxy. Leave empty for IAP SSH loopback mode."
  type        = string
  default     = ""

  validation {
    condition     = var.hub_public_url == "" || startswith(var.hub_public_url, "https://")
    error_message = "hub_public_url must be empty (loopback mode) or start with https://."
  }
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
