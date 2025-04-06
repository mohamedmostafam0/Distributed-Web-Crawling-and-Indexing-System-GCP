# terraform-crawler-infra/network.tf

# --- VPC Network ---
resource "google_compute_network" "main" {
  name                    = var.network_name
  auto_create_subnetworks = false               # Recommended: Create subnetworks manually
  routing_mode            = "REGIONAL"          # Or "GLOBAL"
  project                 = var.gcp_project_id
  description             = "VPC for the web crawler application"
}

# --- Subnetwork ---
resource "google_compute_subnetwork" "main" {
  name          = var.subnetwork_name
  ip_cidr_range = var.subnetwork_cidr
  region        = var.gcp_region
  network       = google_compute_network.main.id
  project       = var.gcp_project_id
  description   = "Primary subnetwork for web crawler instances"
}

# --- Firewall Rules ---

# Allow SSH from specified IPs to any instance (can be refined with tags)
resource "google_compute_firewall" "allow_ssh" {
  name    = "${var.project_prefix}-allow-ssh"
  network = google_compute_network.main.name
  project = var.gcp_project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.allowed_ssh_ips
  description   = "Allow SSH access from specified source IPs"
}

# Allow ALL internal traffic between tagged instances
# Consider restricting ports and protocols for production
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.project_prefix}-allow-internal"
  network = google_compute_network.main.name
  project = var.gcp_project_id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"] # Allow all TCP ports
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"] # Allow all UDP ports
  }
  
  allow {
    protocol = "icmp" # Allow ping, etc.
  }

  # Apply to traffic originating FROM instances with any of these tags
  source_tags = [
    var.master_network_tag,
    var.crawler_network_tag,
    var.indexer_network_tag
  ]

  # Apply to traffic destined TO instances with any of these tags
  target_tags = [
    var.master_network_tag,
    var.crawler_network_tag,
    var.indexer_network_tag
  ]
  description = "Allow all internal TCP/UDP/ICMP between tagged crawler components"
}

# Allow egress traffic from all instances (GCP usually has an implied allow egress by default)
# This rule makes it explicit if default egress is ever changed or for clarity.
resource "google_compute_firewall" "allow_egress" {
  name    = "${var.project_prefix}-allow-egress"
  network = google_compute_network.main.name
  project = var.gcp_project_id
  direction = "EGRESS" # Specify egress direction

  allow {
    protocol = "all" # Allow all protocols
  }

  destination_ranges = ["0.0.0.0/0"] # Allow traffic to any destination
  description = "Allow all outbound traffic from all instances"
}