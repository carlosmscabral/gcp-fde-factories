# Stage 01 outputs consumed by Stage 02 (02-factory-runtime) and Stage 03 (03-hub-bootstrap).

output "hub_project_id" {
  value = var.hub_project_id
}

output "inference_project_id" {
  value = var.inference_project_id
}

output "sandbox_project_id" {
  value = var.sandbox_project_id
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

output "vpc_self_link" {
  value = var.create_custom_vpc ? google_compute_network.scion_vpc[0].self_link : null
}

output "subnet_self_link" {
  value = var.create_custom_vpc ? google_compute_subnetwork.scion_subnet[0].self_link : var.existing_subnet_self_link
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.hub_project_id}/${google_artifact_registry_repository.scion_images.repository_id}"
}

output "hub_sa_email" {
  value = google_service_account.scion_hub.email
}

output "iap_proxy_sa_email" {
  value = google_service_account.iap_proxy.email
}

output "worker_sa_email" {
  value = google_service_account.worker.email
}

output "sandbox_deployer_sa_email" {
  value = google_service_account.sandbox_deployer.email
}

output "sandbox_evaluator_sa_email" {
  value = google_service_account.sandbox_evaluator.email
}

output "sandbox_janitor_sa_email" {
  value = google_service_account.sandbox_janitor.email
}

output "release_builder_sa_email" {
  value = google_service_account.release_builder.email
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
