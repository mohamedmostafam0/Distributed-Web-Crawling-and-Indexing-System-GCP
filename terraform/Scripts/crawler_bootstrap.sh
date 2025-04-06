#!/bin/bash -xe
# Crawler Node Bootstrap Script (GCP)
# WARNING: Basic template. Customize heavily!

# Variables from Terraform templatefile() are available
# Example: MASTER_IP="${master_internal_ip}"

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
METADATA_FLAVOR_HEADER="Metadata-Flavor: Google"

echo "Starting Crawler Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'
echo "Master Internal IP received: ${master_internal_ip}"

# --- Install Packages ---
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git curl

# --- Application Setup ---
# Install Python dependencies
# cd /path/to/your/cloned/repo
# sudo pip3 install -r requirements.txt

# Clone your application code
# git clone https://your-repo-url.com/project.git /opt/webcrawler-app
# cd /opt/webcrawler-app

# Configure environment variables / application config using MASTER_IP
# echo "master_host=${master_internal_ip}" >> /opt/webcrawler-app/config.ini
# export QUEUE_PROJECT_ID="${var.gcp_project_id}"
# export QUEUE_SUBSCRIPTION_NAME="your-subscription-name"

# Setup systemd service for the crawler worker process
# Create /etc/systemd/system/crawler-worker.service
# sudo systemctl enable crawler-worker
# sudo systemctl start crawler-worker

echo "Finished Crawler Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'