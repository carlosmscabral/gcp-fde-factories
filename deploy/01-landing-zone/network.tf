# Non-default VPC network, Private Google Access, Cloud NAT, firewalls, and Artifact Registry.
# Avoids dependency on the default VPC so hardened customer organizations deploy without patches.

resource "google_compute_network" "scion_vpc" {
  count = var.create_custom_vpc ? 1 : 0

  project                 = var.hub_project_id
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.enabled]
}

resource "google_compute_subnetwork" "scion_subnet" {
  count = var.create_custom_vpc ? 1 : 0

  project                  = var.hub_project_id
  name                     = "${var.name_prefix}-subnet"
  region                   = var.region
  network                  = google_compute_network.scion_vpc[0].id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_router" "scion_router" {
  count = var.create_custom_vpc ? 1 : 0

  project = var.hub_project_id
  name    = "${var.name_prefix}-router"
  region  = var.region
  network = google_compute_network.scion_vpc[0].id
}

resource "google_compute_router_nat" "scion_nat" {
  count = var.create_custom_vpc ? 1 : 0

  project                            = var.hub_project_id
  name                               = "${var.name_prefix}-nat"
  router                             = google_compute_router.scion_router[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_firewall" "allow_iap_ssh" {
  count = var.create_custom_vpc ? 1 : 0

  project     = var.hub_project_id
  name        = "${var.name_prefix}-allow-iap-ssh"
  network     = google_compute_network.scion_vpc[0].name
  direction   = "INGRESS"
  target_tags = ["${var.name_prefix}-hub"]

  # Official Google Cloud IAP TCP forwarding CIDR range.
  source_ranges = ["35.235.240.0/20"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "allow_proxy_hub" {
  count = var.create_custom_vpc ? 1 : 0

  project       = var.hub_project_id
  name          = "${var.name_prefix}-allow-proxy-8080"
  network       = google_compute_network.scion_vpc[0].name
  direction     = "INGRESS"
  target_tags   = ["${var.name_prefix}-hub"]
  source_ranges = [var.subnet_cidr]

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
}

resource "google_artifact_registry_repository" "scion_images" {
  project       = var.hub_project_id
  location      = var.region
  repository_id = "${var.name_prefix}-images"
  format        = "DOCKER"
  description   = "Digest-pinned Scion harness images and FDE pack layers."

  depends_on = [google_project_service.enabled]
}
