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

variable "scion_binary_sha256" {
  description = "Pinned SHA-256 hex digest of scion-linux-amd64.tar.gz matching compat.yaml (verified offline before extraction)."
  type        = string
  default     = "d210505c58393f68ae719bc6185e71a3f0455caa1dce6e7798d6bc355663e17f"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.scion_binary_sha256))
    error_message = "scion_binary_sha256 must be a 64-character lowercase SHA-256 hex digest."
  }
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
