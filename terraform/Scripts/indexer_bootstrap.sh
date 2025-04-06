#!/bin/bash -xe
# Indexer Node Bootstrap Script (GCP)
# WARNING: Basic template. Customize heavily!

# Variables from Terraform templatefile() are available
# Example: MASTER_IP="${master_internal_ip}"

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
METADATA_FLAVOR_HEADER="Metadata-Flavor: Google"

echo "Starting Indexer Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'
echo "Master Internal IP received: ${master_internal_ip}"

# --- Persistent Disk Setup ---
# The attached disk (device_name = "data-disk") often appears as /dev/sdb
# Use lsblk to confirm the device name for the non-boot disk
DATA_DISK_DEVICE="/dev/sdb" # !! VERIFY THIS on an actual instance !!
INDEX_DIR="/data/index"

echo "Checking disk device: ${DATA_DISK_DEVICE}"
lsblk

# Check if the volume already has a filesystem. !! Be careful !!
if ! sudo file -s ${DATA_DISK_DEVICE} | grep -q filesystem; then
  echo "Formatting ${DATA_DISK_DEVICE} as ext4"
  sudo mkfs.ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard ${DATA_DISK_DEVICE}
else
  echo "${DATA_DISK_DEVICE} already has a filesystem."
fi

# Mount the volume
echo "Creating mount point ${INDEX_DIR}"
sudo mkdir -p ${INDEX_DIR}
echo "Mounting ${DATA_DISK_DEVICE} to ${INDEX_DIR}"
# Add to /etc/fstab for persistence across reboots
UUID=$(sudo blkid -s UUID -o value ${DATA_DISK_DEVICE})
echo "UUID=${UUID}  ${INDEX_DIR}  ext4  discard,defaults,nofail  0  2" | sudo tee -a /etc/fstab
sudo mount -a # Mount all filesystems in fstab (including the new one)
sudo chown ubuntu:ubuntu ${INDEX_DIR} # Change ownership (user might be different)
echo "Filesystem mounted:"
df -h ${INDEX_DIR}
# --- End Persistent Disk Setup ---


# --- Install Packages ---
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git curl

# --- Application Setup ---
# Install Python dependencies (e.g., Elasticsearch client, DB client)
# cd /path/to/your/cloned/repo
# sudo pip3 install -r requirements.txt

# Clone your application code
# git clone https://your-repo-url.com/project.git /opt/webcrawler-app
# cd /opt/webcrawler-app

# Configure environment variables / application config using MASTER_IP
# echo "master_host=${master_internal_ip}" >> /opt/webcrawler-app/config.ini
# export INDEX_PATH="${INDEX_DIR}"
# export QUEUE_PROJECT_ID="${var.gcp_project_id}"
# export QUEUE_SUBSCRIPTION_NAME="your-data-subscription-name"
# export SEARCH_SERVICE_ENDPOINT="your-search-service-endpoint" # e.g., Elasticsearch

# Setup systemd service for the indexer worker process
# Create /etc/systemd/system/indexer-worker.service
# sudo systemctl enable indexer-worker
# sudo systemctl start indexer-worker

echo "Finished Indexer Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'