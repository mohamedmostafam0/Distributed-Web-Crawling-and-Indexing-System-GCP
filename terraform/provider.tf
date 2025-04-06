# terraform-crawler-infra/provider.tf

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0" # Use a recent version
    }
  }
  required_version = ">= 1.3"
}

provider "google" {
  project = var.gcp_project_id

  region  = var.gcp_region
  # Credentials can be configured via:
  # 1. Google Cloud SDK (gcloud auth application-default login) - Recommended for local use
  # 2. Service Account Key file (GOOGLE_APPLICATION_CREDENTIALS env var) - Use with caution
  # 3. Compute Engine metadata (when running Terraform on a GCE instance)
}