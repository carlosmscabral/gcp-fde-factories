# Input variables for Stage 01 (Landing Zone).
# Three independent project IDs support 3-project (prod), 2-project (hub==inference + sandbox), or 1-project topologies.

variable "hub_project_id" {
  description = "Google Cloud project ID hosting the Scion Hub and Artifact Registry."
  type        = string
}

variable "inference_project_id" {
  description = "Google Cloud project ID dedicated to Vertex AI inference and FinOps budget controls."
  type        = string
}

variable "enable_sandbox_project" {
  description = "If true (recommended default), provisions disposable Sandbox project SAs, IAM roles, and staging bindings. Set false for exceptional CI-only or deploy_target=none topologies without a Sandbox project."
  type        = bool
  default     = true
}

variable "sandbox_project_id" {
  description = "Disposable Google Cloud project ID hosting ephemeral Sandbox deployments and evaluations. Optional only when enable_sandbox_project is false."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_sandbox_project || length(trimspace(var.sandbox_project_id)) > 0
    error_message = "Set sandbox_project_id when enable_sandbox_project is true."
  }
}

variable "region" {
  description = "Primary region for networking, Artifact Registry, and Cloud Run services."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Primary zone for the Lite Single-VM Scion Hub."
  type        = string
  default     = "us-central1-a"
}

variable "name_prefix" {
  description = "Short prefix applied to network, registry, bucket, and service account names."
  type        = string
  default     = "gecx-factory"
}

variable "create_custom_vpc" {
  description = "If true, creates a dedicated non-default VPC and Cloud NAT. Set false for customer Shared VPC."
  type        = bool
  default     = true
}

variable "existing_subnet_self_link" {
  description = "Existing custom or Shared VPC subnet self_link required when create_custom_vpc is false."
  type        = string
  default     = ""

  validation {
    condition     = var.create_custom_vpc || length(trimspace(var.existing_subnet_self_link)) > 0
    error_message = "Set existing_subnet_self_link when create_custom_vpc is false."
  }
}

variable "subnet_cidr" {
  description = "IPv4 CIDR range for the custom Scion Hub subnet."
  type        = string
  default     = "10.42.0.0/20"
}

variable "billing_account_id" {
  description = "Billing account ID used to attach the Inference Project budget alert."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly budget threshold in USD for the Inference Project alert and IAM kill-switch."
  type        = number
  default     = 500
}

variable "enable_budget_pubsub_topic" {
  description = "If true, attaches the Hub Pub/Sub topic to the Billing Budget. Set false in orgs enforcing Domain Restricted Sharing (constraints/iam.allowedPolicyMemberDomains) until billing-budget-alert@system.gserviceaccount.com is permitted (HC-04 F2)."
  type        = bool
  default     = true
}

variable "factory_operator_members" {
  description = "IAM members (group: or user:) granted roles/iam.serviceAccountUser on the 3 assignable SAs for gcp_iam_check_mode=enforce."
  type        = list(string)
  default     = []
}

variable "enable_gecx_sandbox_roles" {
  description = "If true, enables CES and TTS APIs and provisions explicit non-wildcard GECX Sandbox custom roles."
  type        = bool
  default     = true
}

variable "enable_adk_sandbox_roles" {
  description = "If true, enables Discovery Engine and Cloud Run APIs and adds explicit non-wildcard ADK Agent Engine, Cloud Run, and Gemini Enterprise Sandbox custom roles."
  type        = bool
  default     = false
}

variable "enable_generic_sandbox_roles" {
  description = "If true (with enable_sandbox_project=true), enables narrow non-wildcard Cloud Run and Cloud Build Sandbox custom roles for packs/generic without ADK or CES permissions."
  type        = bool
  default     = false
}

variable "enable_agent_engine_re_ar_reader" {
  description = "If true, grants roles/artifactregistry.reader on hub_project_id to the sandbox Reasoning Engine service agent (gcp-sa-aiplatform-re) once materialized."
  type        = bool
  default     = false
}

variable "enable_gke_api" {
  description = "If true, enables container.googleapis.com on hub_project_id for the HA GKE runtime profile."
  type        = bool
  default     = false
}

variable "enable_kaizen_gcp_obs" {
  description = "If true, creates an optional read-only Kaizen telemetry Service Account with Monitoring and Logging Viewer roles (Tier B)."
  type        = bool
  default     = false
}

variable "enable_github_wif" {
  description = "If true, provisions a keyless GitHub Actions Workload Identity Federation pool and provider scoped strictly to github_repository and github_repositories."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "Primary GitHub repository slug (owner/repo) authorized to impersonate Sandbox Evaluator and Janitor SAs via WIF when enable_github_wif is true."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "Set github_repository to 'owner/repo' (or leave empty when using github_repositories)."
  }
}

variable "github_repositories" {
  description = "Optional list of GitHub repository slugs (owner/repo) authorized on a shared multi-pack Hub WIF pool when enable_github_wif is true (HC-11 F2)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for repo in var.github_repositories : can(regex("^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo))])
    error_message = "Every entry in github_repositories must match 'owner/repo'."
  }
}
