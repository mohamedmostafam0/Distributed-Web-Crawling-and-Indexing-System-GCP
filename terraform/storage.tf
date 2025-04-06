# terraform-crawler-infra/storage.tf

# Use a random suffix to help ensure global bucket name uniqueness
resource "random_id" "bucket_suffix" {
  byte_length = 4 # Creates an 8-character hex suffix
}

# Define the Google Cloud Storage Bucket
resource "google_storage_bucket" "webcrawler_data" {
  name          = "${var.project_prefix}-data-${random_id.bucket_suffix.hex}" # Enforces global uniqueness
  location      = var.gcp_region # Deploy bucket in the same region as instances
  project       = var.gcp_project_id
  storage_class = "STANDARD" # Good default for frequently accessed data

  # Recommended: Enforce uniform bucket-level access for simpler IAM
  uniform_bucket_level_access = true

  # Enable versioning to keep history of objects (good for backups/recovery)
  versioning {
    enabled = true
  }

  # Apply common labels
  labels = merge(var.common_labels, { component = "data-storage" })

  # Optional: Lifecycle rules to manage object versions or transition storage classes
  # lifecycle_rule {
  #   condition {
  #     age = 30 // days
  #   }
  #   action {
  #     type = "Delete" // Or "SetStorageClass" to NEARLINE, COLDLINE, ARCHIVE
  #   }
  # }
}


# Grant the instance service account permissions on the specific GCS bucket
resource "google_storage_bucket_iam_member" "instance_sa_gcs_access" {
  bucket = google_storage_bucket.webcrawler_data.name
  role   = "roles/storage.objectAdmin" # Broad access: Create, Read, Update, Delete
  member = "serviceAccount:${google_service_account.instance_sa.email}"

  # Use roles/storage.objectViewer and roles/storage.objectCreator for more granular control if needed
}

# Ensure the main IAM bindings for the SA are created before bucket-level binding
# (May not be strictly necessary but good practice)
# Add this depends_on within the google_storage_bucket_iam_member resource if needed:
# depends_on = [
#   google_project_iam_member.logging_writer,
#   google_project_iam_member.monitoring_writer,
# ]
