# terraform.tfvars

gcp_project_id = "your-gcp-project-id" # Replace with your actual GCP Project ID
# gcp_region = "us-central1" # Default value from variables.tf will be used if commented out
# gcp_zone = "us-central1-a" # Default value from variables.tf will be used if commented out

# project_prefix = "webcrawler" # Default value from variables.tf will be used if commented out

# network_name = "webcrawler-vpc" # Default value from variables.tf will be used if commented out
# subnetwork_name = "webcrawler-subnet" # Default value from variables.tf will be used if commented out
# subnetwork_cidr = "10.10.0.0/20" # Default value from variables.tf will be used if commented out

# master_machine_type = "e2-micro" # Default value from variables.tf will be used if commented out
# crawler_machine_type = "e2-micro" # Default value from variables.tf will be used if commented out
# indexer_machine_type = "e2-micro" # Default value from variables.tf will be used if commented out

# crawler_count = 3 # Default value from variables.tf will be used if commented out
# indexer_count = 2 # Default value from variables.tf will be used if commented out

# os_image_project = "ubuntu-os-cloud" # Default value from variables.tf will be used if commented out
# os_image_family = "ubuntu-2204-lts" # Default value from variables.tf will be used if commented out

# indexer_disk_size_gb = 50 # Default value from variables.tf will be used if commented out
# indexer_disk_type = "pd-balanced" # Default value from variables.tf will be used if commented out

allowed_ssh_ips = ["YOUR_PUBLIC_IP/32"] # Replace with your actual public IP address or a wider range if needed

# common_labels = { # Default value from variables.tf will be used if commented out
#   project     = "distributed-web-crawler"
#   managed-by  = "terraform"
#   environment = "development"
# }

# master_network_tag = "master-node" # Default value from variables.tf will be used if commented out
# crawler_network_tag = "crawler-node" # Default value from variables.tf will be used if commented out
# indexer_network_tag = "indexer-node" # Default value from variables.tf will be used if commented out

pubsub_topic_name = "crawler-topic" # You can customize the Pub/Sub topic name
pubsub_subscription_name = "crawler-subscription" # You can customize the Pub/Sub subscription name