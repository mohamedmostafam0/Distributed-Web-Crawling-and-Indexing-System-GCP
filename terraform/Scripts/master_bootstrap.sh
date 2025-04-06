#!/bin/bash -xe
# Master Node Bootstrap Script (GCP)
# WARNING: Basic template. Customize heavily!

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
METADATA_FLAVOR_HEADER="Metadata-Flavor: Google"

echo "Starting Master Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'

# --- Get Instance Metadata ---
# INTERNAL_IP=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/network-interfaces/0/ip)
# ZONE=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/zone | cut -d'/' -f4)
# echo "Running in Zone: ${ZONE}, Internal IP: ${INTERNAL_IP}"

# --- Install Packages ---
sudo apt-get update -y
# sudo apt-get upgrade -y # Consider if needed, can increase startup time
sudo apt-get install -y python3 python3-pip git curl wget unzip tree apt-transport-https ca-certificates gnupg

# --- Install Google Cloud CLI (Optional but often useful) ---
# if ! type gcloud > /dev/null; then
#     echo "Installing Google Cloud CLI"
#     echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
#     curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo tee /usr/share/keyrings/cloud.google.gpg > /dev/null
#     sudo apt-get update -y && sudo apt-get install -y google-cloud-cli
# fi

# --- Application Setup ---
# Install Python dependencies
# cd /path/to/your/cloned/repo
# sudo pip3 install -r requirements.txt

# Clone your application code
# git clone https://your-repo-url.com/project.git /opt/webcrawler-app
# cd /opt/webcrawler-app

# Configure environment variables / application config
# export QUEUE_PROJECT_ID="${var.gcp_project_id}" # Get from TF or directly
# export QUEUE_TOPIC_NAME="your-topic-name"
# export GCS_BUCKET_NAME="your-bucket-name"

# Setup systemd service for the master process
# Create /etc/systemd/system/crawler-master.service
# sudo systemctl enable crawler-master
# sudo systemctl start crawler-master

echo "Finished Master Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'