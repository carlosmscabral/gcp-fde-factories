# FinOps budget alerts targeting the Inference Project and Sandbox ephemeral staging bucket.
# Budget thresholds fire at 70% (alert) and 90% (IAM revocation kill-switch trigger).
# Grants roles/storage.objectUser to the CES Service Agent on the staging bucket (Spike fix).

data "google_project" "inference" {
  project_id = var.inference_project_id
}

data "google_project" "sandbox" {
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

  # Attach Pub/Sub only when Domain Restricted Sharing permits billing-budget-alert@system.gserviceaccount.com (HC-04 F2).
  all_updates_rule {
    pubsub_topic                   = var.enable_budget_pubsub_topic ? google_pubsub_topic.budget_alerts.id : null
    schema_version                 = var.enable_budget_pubsub_topic ? "1.0" : null
    disable_default_iam_recipients = false
  }

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket" "sandbox_staging" {
  project                     = var.sandbox_project_id
  name                        = "${var.sandbox_project_id}-${var.name_prefix}-staging"
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = true

  # Remove ephemeral export, import, and audio evaluation files automatically after 1 day.
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
  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.sandbox_deployer.email}"
}

resource "google_storage_bucket_iam_member" "deployer_staging_bucket_view" {
  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.bucketViewer"
  member = "serviceAccount:${google_service_account.sandbox_deployer.email}"
}

resource "google_storage_bucket_iam_member" "evaluator_staging_ro" {
  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.sandbox_evaluator.email}"
}

# Cloud Build SA needs staging read/write access when --gcs-source-staging-dir and --gcs-log-dir target this bucket.
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

# Explicitly materialize the CES Service Agent on brand-new projects before binding staging IAM (HC-01 F3).
resource "google_project_service_identity" "ces_service_agent" {
  provider = google-beta
  count    = var.enable_gecx_sandbox_roles ? 1 : 0

  project = var.sandbox_project_id
  service = "ces.googleapis.com"

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket_iam_member" "ces_service_agent_staging" {
  count = var.enable_gecx_sandbox_roles ? 1 : 0

  bucket = google_storage_bucket.sandbox_staging.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_project_service_identity.ces_service_agent[0].email}"

  depends_on = [google_project_service_identity.ces_service_agent]
}
