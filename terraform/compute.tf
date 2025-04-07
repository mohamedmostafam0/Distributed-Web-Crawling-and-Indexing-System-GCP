# terraform-crawler-infra/compute.tf

# --- Service Account for Instances ---
# Assign minimal roles needed. Add roles for Pub/Sub, Storage, etc. as required by your app.
resource "google_service_account" "instance_sa" {
  account_id   = "${var.project_prefix}-instance-sa"
  display_name = "Service Account for Web Crawler Instances"
  project      = var.gcp_project_id
}

# Grant roles needed for basic operations (logging, monitoring)
resource "google_project_iam_member" "logging_writer" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.instance_sa.email}"
}

resource "google_project_iam_member" "monitoring_writer" {
  project = var.gcp_project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.instance_sa.email}"
}

# Add roles for specific services (Uncomment and adjust as needed):
resource "google_project_iam_member" "pubsub_publisher" {
  project = var.gcp_project_id
  role    = "roles/pubsub.publisher" # Or subscriber, viewer, etc.
  member  = "serviceAccount:${google_service_account.instance_sa.email}"
}

# resource "google_project_iam_member" "storage_object_admin" {
#   project = var.gcp_project_id
#   role    = "roles/storage.objectAdmin" # Adjust role as needed
#   member  = "serviceAccount:${google_service_account.instance_sa.email}"
# }


# --- Data Disk for Indexers ---
resource "google_compute_disk" "indexer_data_disk" {
  count   = var.indexer_count
  name    = "${var.project_prefix}-indexer-data-disk-${count.index + 1}"
  type    = var.indexer_disk_type
  zone    = var.gcp_zone
  size    = var.indexer_disk_size_gb
  project = var.gcp_project_id
  labels  = merge(var.common_labels, { role = "indexer-data" })
  # physical_block_size_bytes = 4096 # Default
}


# --- Master Node Instance ---
resource "google_compute_instance" "master" {
  name         = "${var.project_prefix}-master"
  machine_type = var.master_machine_type
  zone         = var.gcp_zone
  project      = var.gcp_project_id
  tags         = [var.master_network_tag] # Tag for firewall rules
  labels       = merge(var.common_labels, { role = "master" })

  boot_disk {
    initialize_params {
      image = "${var.os_image_project}/${var.os_image_family}"
      size  = 20 # Boot disk size in GB
      type = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    # Add empty access_config to assign an ephemeral public IP
    access_config {}
  }

  # Use templatefile to render the bootstrap script
  metadata_startup_script = templatefile("${path.module}/scripts/master_bootstrap.sh", {
    # Pass any required variables to the script here
  })

  service_account {
    email  = google_service_account.instance_sa.email
    scopes = ["cloud-platform"] # Allows access to most GCP APIs based on IAM roles
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE" # Or "TERMINATE"
  }

  allow_stopping_for_update = true # Allows Terraform to stop/start instance for some changes

  depends_on = [
    # Ensure SA roles are assigned before instance creation attempts API calls
    google_project_iam_member.logging_writer,
    google_project_iam_member.monitoring_writer,
    google_project_iam_member.pubsub_publisher, # Add dependencies for other roles
    # google_project_iam_member.storage_object_admin,
  ]
}

# --- Crawler Node Instances ---
resource "google_compute_instance" "crawler" {
  count        = var.crawler_count
  name         = "${var.project_prefix}-crawler-${count.index + 1}"
  machine_type = var.crawler_machine_type
  zone         = var.gcp_zone
  project      = var.gcp_project_id
  tags         = [var.crawler_network_tag] # Tag for firewall rules
  labels       = merge(var.common_labels, { role = "crawler" })

  boot_disk {
    initialize_params {
      image = "${var.os_image_project}/${var.os_image_family}"
      size  = 20
      type = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    access_config {} # Assign public IP
  }

  metadata_startup_script = templatefile("${path.module}/scripts/crawler_bootstrap.sh", {
    master_internal_ip = google_compute_instance.master.network_interface[0].network_ip
    # Add other vars (e.g., pubsub topic name)
  })

  service_account {
    email  = google_service_account.instance_sa.email
    scopes = ["cloud-platform"]
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }

  allow_stopping_for_update = true

  depends_on = [
    google_compute_instance.master, # Ensure master IP is available
    google_project_iam_member.logging_writer,
    google_project_iam_member.monitoring_writer,
  ]
}

# --- Indexer Node Instances ---
resource "google_compute_instance" "indexer" {
  count        = var.indexer_count
  name         = "${var.project_prefix}-indexer-${count.index + 1}"
  machine_type = var.indexer_machine_type
  zone         = var.gcp_zone
  project      = var.gcp_project_id
  tags         = [var.indexer_network_tag] # Tag for firewall rules
  labels       = merge(var.common_labels, { role = "indexer" })

  boot_disk {
    initialize_params {
      image = "${var.os_image_project}/${var.os_image_family}"
      size  = 20
      type = "pd-balanced"
    }
  }

  # Attach the pre-created data disk
  attached_disk {
    source      = google_compute_disk.indexer_data_disk[count.index].id
    device_name = "data-disk" # Arbitrary name, will likely map to /dev/sdb
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.id
    access_config {} # Assign public IP
  }

  metadata_startup_script = templatefile("${path.module}/scripts/indexer_bootstrap.sh", {
    master_internal_ip = google_compute_instance.master.network_interface[0].network_ip
    # Add other vars (e.g., pubsub topic name, storage bucket)
  })

  service_account {
    email  = google_service_account.instance_sa.email
    scopes = ["cloud-platform"]
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }

  allow_stopping_for_update = true

  depends_on = [
    google_compute_instance.master,
    google_project_iam_member.logging_writer,
    google_project_iam_member.monitoring_writer,
  ]
}