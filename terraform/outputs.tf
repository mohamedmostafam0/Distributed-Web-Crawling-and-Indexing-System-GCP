# terraform-crawler-infra/outputs.tf

output "master_external_ip" {
  description = "External IP address of the Master node."
  value       = google_compute_instance.master.network_interface[0].access_config[0].nat_ip
}

output "master_internal_ip" {
  description = "Internal IP address of the Master node."
  value       = google_compute_instance.master.network_interface[0].network_ip
}

output "crawler_external_ips" {
  description = "List of External IP addresses of the Crawler nodes."
  value       = google_compute_instance.crawler[*].network_interface[0].access_config[0].nat_ip
}

output "crawler_internal_ips" {
  description = "List of Internal IP addresses of the Crawler nodes."
  value       = google_compute_instance.crawler[*].network_interface[0].network_ip
}

output "indexer_external_ips" {
  description = "List of External IP addresses of the Indexer nodes."
  value       = google_compute_instance.indexer[*].network_interface[0].access_config[0].nat_ip
}

output "indexer_internal_ips" {
  description = "List of Internal IP addresses of the Indexer nodes."
  value       = google_compute_instance.indexer[*].network_interface[0].network_ip
}

output "network_name" {
  description = "Name of the VPC network created."
  value       = google_compute_network.main.name
}

output "subnetwork_name" {
  description = "Name of the subnetwork created."
  value       = google_compute_subnetwork.main.name
}

output "ssh_command_master" {
  description = "Example command to SSH into the Master node using gcloud."
  value       = "gcloud compute ssh --project ${var.gcp_project_id} --zone ${var.gcp_zone} ${google_compute_instance.master.name}"
}

output "instance_service_account_email" {
  description = "Email of the service account assigned to the instances."
  value       = google_service_account.instance_sa.email
}

output "firewall_rule_names" {
  description = "Names of the created firewall rules."
  value = {
    allow_ssh      = google_compute_firewall.allow_ssh.name
    allow_internal = google_compute_firewall.allow_internal.name
    allow_egress   = google_compute_firewall.allow_egress.name
  }
}

output "gcs_bucket_name" {
  description = "Name of the Google Cloud Storage bucket created for crawler data."
  value       = google_storage_bucket.webcrawler_data.name
}
