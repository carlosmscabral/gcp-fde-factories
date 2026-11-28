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

variable "enable_delta_watcher" {
  description = "If true, deploys the private Cloud Run External Delta Watcher and Cloud Scheduler tick job reaching the Hub VM via Direct VPC Egress (Issue #2)."
  type        = bool
  default     = false
}

variable "delta_watcher_image" {
  description = "Digest-pinned Artifact Registry image built from scripts/delta-watcher/Dockerfile."
  type        = string
  default     = ""
}

variable "delta_watcher_sa_email" {
  description = "Delta Watcher Cloud Run runtime Service Account email from Stage 01."
  type        = string
  default     = ""
}

variable "delta_watcher_invoker_sa_email" {
  description = "Delta Watcher Cloud Scheduler OIDC invoker Service Account email from Stage 01."
  type        = string
  default     = ""
}

variable "delta_watcher_state_bucket" {
  description = "Hub-project GCS bucket name from Stage 01 for Delta Watcher optimistic-concurrency cursors."
  type        = string
  default     = ""
}

variable "delta_watcher_tracker_repo" {
  description = "Target external tracker repository slug (owner/repo) polled by the Delta Watcher."
  type        = string
  default     = ""
}

variable "delta_watcher_token_secret_id" {
  description = "Optional Secret Manager secret ID in hub_project_id mounted as GITHUB_TOKEN."
  type        = string
  default     = ""
}

variable "delta_watcher_scion_project_id" {
  description = "Optional Scion Hub project UUID scoped for coordinator wakeup messages."
  type        = string
  default     = ""
}

variable "delta_watcher_coordinator_agent" {
  description = "Scion coordinator agent slug notified by the External Delta Watcher. Must match kaizen.coordinator_agent in .factory/hub-project.yaml (for example adk-coordinator, gecx-coordinator, or sw-coordinator)."
  type        = string
  default     = "coordinator"
}

variable "delta_watcher_paused" {
  description = "If true, pauses new issue dispatches while still forwarding human replies and PR action signals."
  type        = bool
  default     = false
}

variable "delta_watcher_github_graphql_url" {
  description = "Optional custom GitHub GraphQL endpoint for GitHub Enterprise Server or GHEC data residency."
  type        = string
  default     = ""
}

variable "delta_watcher_allowed_associations" {
  description = "Optional comma-separated GitHub authorAssociation allowlist for Delta Watcher comments and PR signals (defaults to OWNER,MEMBER,COLLABORATOR)."
  type        = string
  default     = ""
}

variable "delta_watcher_cadence_cron" {
  description = "Cloud Scheduler cron schedule triggering POST /tick on the private Delta Watcher service."
  type        = string
  default     = "*/5 * * * *"
}

variable "delta_watcher_time_zone" {
  description = "IANA time zone applied to the Delta Watcher Cloud Scheduler job."
  type        = string
  default     = "America/Sao_Paulo"
}

variable "delta_watcher_release_label" {
  description = "Explicit opt-in tracker label releasing open issues to the factory."
  type        = string
  default     = "factory:ready"
}

variable "delta_watcher_hold_label" {
  description = "Veto tracker label suppressing new issue dispatches."
  type        = string
  default     = "factory:hold"
}

variable "delta_watcher_scope_label" {
  description = "Optional multi-factory scope label required alongside the release label."
  type        = string
  default     = ""
}

variable "delta_watcher_max_concurrent_issues" {
  description = "SEP portfolio capacity cap for simultaneously dispatched open issues (1 to 3)."
  type        = number
  default     = 2

  validation {
    condition     = var.delta_watcher_max_concurrent_issues >= 1 && var.delta_watcher_max_concurrent_issues <= 3
    error_message = "delta_watcher_max_concurrent_issues must stay within the SEP empirical ceiling (1 to 3)."
  }
}
