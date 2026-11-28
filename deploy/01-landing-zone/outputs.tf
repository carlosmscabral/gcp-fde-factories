# Stage 01 outputs consumed by Stage 02 (02-factory-runtime) and Stage 03 (03-hub-bootstrap).

output "hub_project_id" {
  value = var.hub_project_id
}

output "inference_project_id" {
  value = var.inference_project_id
}

output "sandbox_project_id" {
  value = var.enable_sandbox_project ? var.sandbox_project_id : null
}

output "sandbox_project_number" {
  value = var.enable_sandbox_project ? data.google_project.sandbox[0].number : null
}

output "region" {
  value = var.region
}

output "zone" {
  value = var.zone
}

output "name_prefix" {
  value = var.name_prefix
}

output "vpc_name" {
  value = var.create_custom_vpc ? google_compute_network.scion_vpc[0].name : null
}

output "vpc_self_link" {
  value = var.create_custom_vpc ? google_compute_network.scion_vpc[0].self_link : null
}

output "subnet_self_link" {
  value = var.create_custom_vpc ? google_compute_subnetwork.scion_subnet[0].self_link : var.existing_subnet_self_link
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.hub_project_id}/${google_artifact_registry_repository.scion_images.repository_id}"
}

output "sandbox_artifact_registry_url" {
  description = "Disposable Sandbox Artifact Registry URL for autonomous PR container builds (costela H3)."
  value       = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? "${var.region}-docker.pkg.dev/${var.sandbox_project_id}/${google_artifact_registry_repository.sandbox_images[0].repository_id}" : null
}

output "hub_sa_email" {
  value = google_service_account.scion_hub.email
}

output "iap_proxy_sa_email" {
  value = google_service_account.iap_proxy.email
}

output "coordinator_sa_email" {
  value = google_service_account.coordinator.email
}

output "worker_sa_email" {
  value = google_service_account.worker.email
}

output "sandbox_deployer_sa_email" {
  value = var.enable_sandbox_project ? google_service_account.sandbox_deployer[0].email : null
}

output "sandbox_evaluator_sa_email" {
  value = var.enable_sandbox_project ? google_service_account.sandbox_evaluator[0].email : null
}

output "sandbox_janitor_sa_email" {
  value = var.enable_sandbox_project ? google_service_account.sandbox_janitor[0].email : null
}

output "release_builder_sa_email" {
  value = google_service_account.release_builder.email
}

output "sandbox_builder_sa_email" {
  description = "Dedicated Sandbox Cloud Build Service Account email isolated from Hub Artifact Registry (costela H3)."
  value       = var.enable_sandbox_project && (var.enable_adk_sandbox_roles || var.enable_generic_sandbox_roles) ? google_service_account.sandbox_builder[0].email : null
}

output "gke_node_sa_email" {
  value = var.enable_gke_api ? google_service_account.gke_node[0].email : null
}

output "adk_runtime_sa_email" {
  value = var.enable_sandbox_project && var.enable_adk_sandbox_roles ? google_service_account.adk_runtime[0].email : null
}

output "budget_pubsub_topic" {
  value = google_pubsub_topic.budget_alerts.id
}

output "sandbox_staging_bucket" {
  value = google_storage_bucket.sandbox_staging.name
}

output "kaizen_viewer_sa_email" {
  value = var.enable_kaizen_gcp_obs ? google_service_account.kaizen_viewer[0].email : null
}

output "github_wif_provider_name" {
  description = "Full Workload Identity Provider resource name for GitHub Actions GCP_WIF_PROVIDER variable."
  value       = var.enable_sandbox_project && var.enable_github_wif ? google_iam_workload_identity_pool_provider.github_oidc[0].name : null
}

output "delta_watcher_sa_email" {
  description = "Least-privilege Cloud Run runtime Service Account email for the External Delta Watcher."
  value       = var.enable_delta_watcher ? google_service_account.delta_watcher[0].email : null
}

output "delta_watcher_invoker_sa_email" {
  description = "Cloud Scheduler OIDC invoker Service Account email for the External Delta Watcher."
  value       = var.enable_delta_watcher ? google_service_account.delta_watcher_invoker[0].email : null
}

output "delta_watcher_state_bucket" {
  description = "Hub-project GCS bucket storing External Delta Watcher optimistic-concurrency cursors."
  value       = var.enable_delta_watcher ? google_storage_bucket.delta_watcher_state[0].name : null
}
