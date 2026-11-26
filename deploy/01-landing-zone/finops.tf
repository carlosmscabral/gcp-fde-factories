# FinOps budget alerts targeting the Inference Project and ephemeral staging bucket.
# Budget thresholds fire at 70% (alert) and 90% (IAM revocation kill-switch trigger).
# Places the staging bucket on sandbox_project_id by default, or on hub_project_id when enable_sandbox_project=false.

locals {
  staging_project_id = var.enable_sandbox_project ? var.sandbox_project_id : var.hub_project_id
}

data "google_project" "inference" {
  project_id = var.inference_project_id
}

data "google_project" "sandbox" {
  count = var.enable_sandbox_project ? 1 : 0

  project_id = var.sandbox_project_id
}

resource "google_pubsub_topic" "budget_alerts" {
  project = var.hub_project_id
  name    = "${var.name_prefix}-budget-alerts"

  depends_on = [google_project_service.enabled]
}

resource "google_billing_budget" "inference_budget" {
  provider        = google-beta
  billing_account = var.billing_account_id
  display_name    = "${var.name_prefix}-inference-${var.inference_project_id}"

  budget_filter {
    projects = ["projects/${data.google_project.inference.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.70
  }

  threshold_rules {
    threshold_percent = 0.90
  }

  # Attach Pub/Sub only when Domain Restricted Sharing permits billing-budget-alert@system.gserviceaccount.com (HC-04 F2, HC-05 F1).
  dynamic "all_updates_rule" {
    for_each = var.enable_budget_pubsub_topic ? [1] : []
    content {
      pubsub_topic                   = google_pubsub_topic.budget_alerts.id
      schema_version                 = "1.0"
      disable_default_iam_recipients = false
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket" "sandbox_staging" {
  project                     = local.staging_project_id
  name                        = "${local.staging_project_id}-${var.name_prefix}-staging"
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = true

  # Remove ephemeral export, import, and Cloud Build source staging files automatically after 1 day.
  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 1
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "deployer_staging_rw" {
  count = var.enable_sandbox_project ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_storage_bucket_iam_member" "deployer_staging_bucket_view" {
  count = var.enable_sandbox_project ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.bucketViewer"
  member = "serviceAccount:${google_service_account.sandbox_deployer[0].email}"
}

resource "google_storage_bucket_iam_member" "evaluator_staging_ro" {
  count = var.enable_sandbox_project ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.sandbox_evaluator[0].email}"
}

# Cloud Build SA needs staging read/write access when --gcs-source-staging-dir targets this bucket.
resource "google_storage_bucket_iam_member" "builder_staging_rw" {
  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.release_builder.email}"
}

resource "google_storage_bucket_iam_member" "builder_staging_bucket_view" {
  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.bucketViewer"
  member = "serviceAccount:${google_service_account.release_builder.email}"
}

resource "google_storage_bucket_iam_member" "sandbox_builder_staging_rw" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sandbox_builder[0].email}"
}

resource "google_storage_bucket_iam_member" "sandbox_builder_staging_bucket_view" {
  count = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.bucketViewer"
  member = "serviceAccount:${google_service_account.sandbox_builder[0].email}"
}

# Explicitly materialize the CES Service Agent on brand-new projects before binding staging IAM (HC-01 F3).
resource "google_project_service_identity" "ces_service_agent" {
  provider = google-beta
  count    = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  service = "ces.googleapis.com"

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "ces_service_agent_staging" {
  count = var.enable_sandbox_project && var.enable_gecx_sandbox_roles ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_project_service_identity.ces_service_agent[0].email}"

  depends_on = [google_project_service_identity.ces_service_agent]
}
