# terraform-crawler-infra/variables.tf

variable "gcp_project_id" {
  description = "GCP Project ID where resources will be created."
  type        = string
  # Example: "my-gcp-project-12345" - Set this in terraform.tfvars or environment
}

variable "gcp_region" {
  description = "GCP region for resources."
  type        = string
  default     = "us-central1"
}

variable "gcp_zone" {
  description = "GCP zone within the region for zonal resources (like VMs)."
  type        = string
  default     = "us-central1-a" # Choose a zone within your region
}

variable "project_prefix" {
  description = "Prefix for naming resources."
  type        = string
  default     = "webcrawler"
}

variable "network_name" {
  description = "Name for the VPC Network."
  type        = string
  default     = "webcrawler-vpc"
}

variable "subnetwork_name" {
  description = "Name for the Subnetwork."
  type        = string
  default     = "webcrawler-subnet"
}

variable "subnetwork_cidr" {
  description = "CIDR block for the Subnetwork."
  type        = string
  default     = "10.10.0.0/20"
}

variable "master_machine_type" {
  description = "GCE machine type for the Master node."
  type        = string
  default     = "e2-micro" # Adjust based on expected load
}

variable "crawler_machine_type" {
  description = "GCE machine type for Crawler nodes."
  type        = string
  default     = "e2-micro" # Adjust based on expected load
}

variable "indexer_machine_type" {
  description = "GCE machine type for Indexer nodes."
  type        = string
  default     = "e2-medium" # Potentially needs more memory/CPU for indexing
}

variable "crawler_count" {
  description = "Number of Crawler nodes."
  type        = number
  default     = 3
}

variable "indexer_count" {
  description = "Number of Indexer nodes."
  type        = number
  default     = 2
}

variable "os_image_project" {
  description = "Project ID where the OS image resides."
  type        = string
  default     = "ubuntu-os-cloud"
}

variable "os_image_family" {
  description = "OS image family to use (e.g., latest Ubuntu LTS)."
  type        = string
  default     = "ubuntu-2204-lts" # Ensure this is available in your region
}

variable "indexer_disk_size_gb" {
  description = "Size in GB for the data Persistent Disk attached to indexer nodes."
  type        = number
  default     = 50 # Adjust based on expected index size
}

variable "indexer_disk_type" {
  description = "Type of the Persistent Disk for indexers."
  type        = string
  default     = "pd-balanced" # Options: pd-standard, pd-balanced, pd-ssd
}

variable "allowed_ssh_ips" {
  description = "List of IP address ranges allowed to SSH into the instances."
  type        = list(string)
  default     = ["0.0.0.0/0"] # WARNING: Allows SSH from anywhere. Restrict this!
                              # Example: ["YOUR_PUBLIC_IP/32"]
}

variable "common_labels" {
  description = "Common labels to apply to all resources."
  type        = map(string)
  default = {
    project     = "distributed-web-crawler"
    managed-by  = "terraform"
    environment = "development"
  }
}

# Network Tags for Firewall Rules
variable "master_network_tag" {
  type    = string
  default = "master-node"
}

variable "crawler_network_tag" {
  type    = string
  default = "crawler-node"
}

variable "indexer_network_tag" {
  type    = string
  default = "indexer-node"
}