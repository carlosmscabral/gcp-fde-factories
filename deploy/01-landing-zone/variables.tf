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

variable "sandbox_project_id" {
  description = "Disposable Google Cloud project ID hosting ephemeral GECX apps and evaluations."
  type        = string
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

variable "factory_operator_members" {
  description = "IAM members (group: or user:) granted roles/iam.serviceAccountUser on the 3 assignable SAs for gcp_iam_check_mode=enforce."
  type        = list(string)
  default     = []
}

variable "enable_adk_sandbox_roles" {
  description = "If true, enables Discovery Engine API and adds explicit non-wildcard ADK Agent Engine and Gemini Enterprise Sandbox custom roles."
  type        = bool
  default     = false
}

variable "enable_kaizen_gcp_obs" {
  description = "If true, creates an optional read-only Kaizen telemetry Service Account with Monitoring and Logging Viewer roles (Tier B)."
  type        = bool
  default     = false
}
