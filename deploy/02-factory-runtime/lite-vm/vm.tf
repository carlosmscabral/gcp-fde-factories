# Hardened Shielded GCE VM running the Lite Single-VM Scion Hub on a non-default subnet.
# Assigns no public external IP so all outbound traffic flows through Stage 01 Cloud NAT.

resource "google_compute_instance" "scion_hub_vm" {
  project      = var.hub_project_id
  name         = "${var.name_prefix}-hub-vm"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["${var.name_prefix}-hub"]

  boot_disk {
    initialize_params {
      image = var.boot_image
      size  = 100
      type  = "pd-balanced"
    }
    kms_key_self_link = var.boot_disk_kms_key_self_link
  }

  network_interface {
    subnetwork = var.subnet_self_link
    # Omit access_config intentionally: enterprise VMs carry no public IP.
  }

  service_account {
    email  = var.hub_sa_email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = {
    enable-oslogin = "TRUE"
    user-data = templatefile("${path.module}/cloud-init.tftpl", {
      scion_version               = var.scion_version
      scion_binary_sha256         = var.scion_binary_sha256
      hub_project_id              = var.hub_project_id
      region                      = var.region
      name_prefix                 = var.name_prefix
      artifact_registry_url       = var.artifact_registry_url
      hub_public_url              = var.hub_public_url
      gcp_iam_deny_unknown_policy = var.gcp_iam_deny_unknown_policy
      admin_emails                = var.admin_emails
      oidc_allowed_domains        = var.oidc_allowed_domains
      oidc_allowed_gcp_projects   = distinct(concat(var.oidc_allowed_gcp_projects, var.enable_delta_watcher ? [var.hub_project_id] : []))
    })
  }

  labels = {
    managed-by = "gcp-fde-factories"
    component  = "scion-hub"
    profile    = "lite-vm"
  }
}
