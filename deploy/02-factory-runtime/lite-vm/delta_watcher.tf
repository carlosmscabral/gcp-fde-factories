# Optional Private Cloud Run + Cloud Scheduler External Delta Watcher (Issue #2).
# Scales to zero between ticks, reaches the private Scion Hub VM over Direct VPC Egress,
# and authenticates via GCP Service Account OIDC with zero inbound internet exposure.

resource "google_cloud_run_v2_service" "delta_watcher" {
  count = var.enable_delta_watcher ? 1 : 0

  project             = var.hub_project_id
  name                = "${var.name_prefix}-delta-watcher"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false

  template {
    service_account = var.delta_watcher_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        subnetwork = var.subnet_self_link
      }
    }

    containers {
      image = var.delta_watcher_image

      env {
        name  = "DELTA_WATCHER_PROVIDER"
        value = "github"
      }
      env {
        name  = "DELTA_WATCHER_REPO"
        value = var.delta_watcher_tracker_repo
      }
      env {
        name  = "DELTA_WATCHER_STATE_BUCKET"
        value = var.delta_watcher_state_bucket
      }
      env {
        name  = "DELTA_WATCHER_STATE_OBJECT"
        value = "delta-watcher/cursor.json"
      }
      env {
        name  = "SCION_HUB_URL"
        value = "http://${google_compute_instance.scion_hub_vm.network_interface[0].network_ip}:8080"
      }
      env {
        name  = "SCION_HUB_PROJECT_ID"
        value = var.delta_watcher_scion_project_id
      }
      env {
        name  = "DELTA_WATCHER_COORDINATOR_AGENT"
        value = var.delta_watcher_coordinator_agent
      }
      env {
        name  = "DELTA_WATCHER_RELEASE_LABEL"
        value = var.delta_watcher_release_label
      }
      env {
        name  = "DELTA_WATCHER_HOLD_LABEL"
        value = var.delta_watcher_hold_label
      }
      env {
        name  = "DELTA_WATCHER_SCOPE_LABEL"
        value = var.delta_watcher_scope_label
      }
      env {
        name  = "DELTA_WATCHER_MAX_CONCURRENT_ISSUES"
        value = tostring(var.delta_watcher_max_concurrent_issues)
      }

      dynamic "env" {
        for_each = length(trimspace(var.delta_watcher_token_secret_id)) > 0 ? [1] : []
        content {
          name = "GITHUB_TOKEN"
          value_source {
            secret_key_ref {
              secret  = var.delta_watcher_token_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(trimspace(var.delta_watcher_image)) > 0 && length(trimspace(var.delta_watcher_sa_email)) > 0 && length(trimspace(var.delta_watcher_invoker_sa_email)) > 0 && length(trimspace(var.delta_watcher_state_bucket)) > 0 && length(trimspace(var.delta_watcher_tracker_repo)) > 0
      error_message = "Set delta_watcher_image, delta_watcher_sa_email, delta_watcher_invoker_sa_email, delta_watcher_state_bucket, and delta_watcher_tracker_repo when enable_delta_watcher is true."
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "delta_watcher_invoker" {
  count = var.enable_delta_watcher ? 1 : 0

  project  = var.hub_project_id
  location = var.region
  name     = google_cloud_run_v2_service.delta_watcher[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.delta_watcher_invoker_sa_email}"
}

resource "google_cloud_scheduler_job" "delta_watcher_tick" {
  count = var.enable_delta_watcher ? 1 : 0

  project          = var.hub_project_id
  region           = var.region
  name             = "${var.name_prefix}-delta-watcher-tick"
  description      = "Triggers deterministic zero-token External Delta Watcher ticks against the private Scion Hub."
  schedule         = var.delta_watcher_cadence_cron
  time_zone        = var.delta_watcher_time_zone
  attempt_deadline = "120s"

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.delta_watcher[0].uri}/tick"

    oidc_token {
      service_account_email = var.delta_watcher_invoker_sa_email
      audience              = google_cloud_run_v2_service.delta_watcher[0].uri
    }
  }
}
