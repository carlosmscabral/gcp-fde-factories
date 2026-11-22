# Stage 01 (Landing Zone) provider versions and Terraform constraints.
# Uses additive IAM bindings only and supports 1-project, 2-project, or 3-project customer topologies.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10.0, < 7.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.10.0, < 7.0.0"
    }
  }
}

provider "google" {
  region                = var.region
  user_project_override = true
  billing_project       = var.hub_project_id
}

provider "google-beta" {
  region                = var.region
  user_project_override = true
  billing_project       = var.hub_project_id
}
