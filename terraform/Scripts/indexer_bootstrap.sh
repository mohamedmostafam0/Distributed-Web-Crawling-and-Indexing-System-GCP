#!/bin/bash -xe
# Indexer Node Bootstrap Script (GCP)
# WARNING: Basic template. Customize heavily!

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
METADATA_FLAVOR_HEADER="Metadata-Flavor: Google"

echo "Starting Indexer Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'

# --- Get Instance Metadata ---
INTERNAL_IP=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/network-interfaces/0/ip)
ZONE=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/zone | cut -d'/' -f4)
echo "Running in Zone: ${ZONE}, Internal IP: ${INTERNAL_IP}"

# --- Persistent Disk Setup ---
DATA_DISK_DEVICE="/dev/sdb" # !! VERIFY THIS on an actual instance !!
INDEX_DIR="/data/index"

echo "Checking disk device: ${DATA_DISK_DEVICE}"
lsblk

# Check if the volume already has a filesystem
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
UUID=$(sudo blkid -s UUID -o value ${DATA_DISK_DEVICE})
echo "UUID=${UUID}  ${INDEX_DIR}  ext4  discard,defaults,nofail  0  2" | sudo tee -a /etc/fstab
sudo mount -a
sudo chown -R $(whoami):$(whoami) ${INDEX_DIR}
echo "Filesystem mounted:"
df -h ${INDEX_DIR}
# --- End Persistent Disk Setup ---

# --- Install Packages ---
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git curl wget unzip tree apt-transport-https ca-certificates gnupg

# --- Setup Application Directory ---
APP_DIR="/opt/webcrawler-app"
sudo mkdir -p ${APP_DIR}
sudo chown -R $(whoami):$(whoami) ${APP_DIR}

# --- Clone Application Code ---
git clone https://github.com/your-repo/webcrawler.git ${APP_DIR}
cd ${APP_DIR}

# --- Setup Python Environment ---
python3 -m pip install --upgrade pip
python3 -m pip install virtualenv
python3 -m virtualenv venv
source venv/bin/activate

# --- Install Python Dependencies ---
pip install -r src/scripts/requirements.txt

# --- Setup Environment Variables ---
# Create .env file from template
cd src/scripts
cp .env.example .env

# Update .env with actual values (these should be passed from Terraform)
cat > .env << EOL
# GCP Configuration
GCP_PROJECT_ID="${var.gcp_project_id}"

# Pub/Sub Configuration
CRAWL_TASKS_TOPIC_ID="${var.crawl_tasks_topic_id}"
CRAWL_TASKS_SUBSCRIPTION_ID="${var.crawl_tasks_subscription_id}"
INDEX_QUEUE_TOPIC_ID="${var.index_queue_topic_id}"

# Google Cloud Storage
GCS_BUCKET_NAME="${var.gcs_bucket_name}"
SEED_FILE_PATH="seeds/start_urls.txt"

# Crawler Configuration
MAX_DEPTH="2"

# Indexer Configuration
INDEX_DIR="${INDEX_DIR}"

# Node Identification
HOSTNAME="indexer-${INTERNAL_IP}"
EOL

# --- Setup Systemd Service ---
sudo tee /etc/systemd/system/indexer-worker.service > /dev/null << EOL
[Unit]
Description=Web Crawler Indexer Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${APP_DIR}/src/scripts
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python3 indexer_node.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# --- Enable and Start Service ---
sudo systemctl daemon-reload
sudo systemctl enable indexer-worker
sudo systemctl start indexer-worker

echo "Finished Indexer Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'