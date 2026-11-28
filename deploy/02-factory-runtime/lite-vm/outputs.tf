# Stage 02 Lite Single-VM outputs for IAP SSH access and Stage 03 Hub bootstrap.

output "hub_vm_name" {
  value = google_compute_instance.scion_hub_vm.name
}

output "hub_internal_ip" {
  value = google_compute_instance.scion_hub_vm.network_interface[0].network_ip
}

output "ssh_iap_command" {
  value = "gcloud compute ssh ${google_compute_instance.scion_hub_vm.name} --zone=${var.zone} --project=${var.hub_project_id} --tunnel-through-iap"
}

output "tunnel_command" {
  value = "gcloud compute ssh ${google_compute_instance.scion_hub_vm.name} --zone=${var.zone} --project=${var.hub_project_id} --tunnel-through-iap -- -N -L 8080:localhost:8080"
}

output "delta_watcher_service_uri" {
  description = "Private Cloud Run URI of the External Delta Watcher when enabled."
  value       = var.enable_delta_watcher ? google_cloud_run_v2_service.delta_watcher[0].uri : null
}

output "delta_watcher_scheduler_job" {
  description = "Cloud Scheduler job name driving External Delta Watcher ticks when enabled."
  value       = var.enable_delta_watcher ? google_cloud_scheduler_job.delta_watcher_tick[0].name : null
}
