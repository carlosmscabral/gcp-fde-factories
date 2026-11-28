# Optional Provider-Agnostic External Delta Watcher IAM and GCS cursor state (Issue #2).
# Strictly additive (enable_delta_watcher = false by default) with zero Vertex AI or Sandbox grants.

resource "google_service_account" "delta_watcher" {
  count = var.enable_delta_watcher ? 1 : 0

  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-delta-watcher"
  display_name = "External Delta Watcher Cloud Run Runtime"

  depends_on = [google_project_service.enabled]
}

resource "google_service_account" "delta_watcher_invoker" {
  count = var.enable_delta_watcher ? 1 : 0

  project      = var.hub_project_id
  account_id   = "${var.name_prefix}-dw-invoker"
  display_name = "External Delta Watcher Cloud Scheduler OIDC Invoker"

  depends_on = [google_project_service.enabled]
}

resource "google_storage_bucket" "delta_watcher_state" {
  count = var.enable_delta_watcher ? 1 : 0

  project                     = var.hub_project_id
  name                        = "${var.hub_project_id}-${var.name_prefix}-dw-state"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.enabled]
}

# Scope cursor writes strictly to the delta-watcher/ prefix via IAM Condition (ifGenerationMatch optimistic locking).
resource "google_storage_bucket_iam_member" "delta_watcher_cursor_rw" {
  count = var.enable_delta_watcher ? 1 : 0

  bucket = google_storage_bucket.delta_watcher_state[0].name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.delta_watcher[0].email}"

  condition {
    title       = "delta_watcher_cursor_prefix_only"
    description = "Restrict Delta Watcher object read/write strictly to delta-watcher/ cursor objects."
    expression  = "resource.name.startsWith(\"projects/_/buckets/${google_storage_bucket.delta_watcher_state[0].name}/objects/delta-watcher/\")"
  }
}

resource "google_project_iam_member" "delta_watcher_logging" {
  count = var.enable_delta_watcher ? 1 : 0

  project = var.hub_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.delta_watcher[0].email}"
}

# Provision the empty Secret Manager metadata container cold-start so IAM binding never hits 404 (HC13-F2).
# Operators add secret versions out-of-band via `gcloud secrets versions add` so no token enters Terraform state.
resource "google_secret_manager_secret" "delta_watcher_tracker_token" {
  count = var.enable_delta_watcher && length(trimspace(var.delta_watcher_token_secret_id)) > 0 ? 1 : 0

  project   = var.hub_project_id
  secret_id = var.delta_watcher_token_secret_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "delta_watcher_tracker_token" {
  count = var.enable_delta_watcher && length(trimspace(var.delta_watcher_token_secret_id)) > 0 ? 1 : 0

  project   = var.hub_project_id
  secret_id = google_secret_manager_secret.delta_watcher_tracker_token[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.delta_watcher[0].email}"
}
