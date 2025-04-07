#!/bin/bash -xe
# Master Node Bootstrap Script (GCP)
# WARNING: Basic template. Customize heavily!

exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
METADATA_FLAVOR_HEADER="Metadata-Flavor: Google"

echo "Starting Master Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'

# --- Get Instance Metadata ---
INTERNAL_IP=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/network-interfaces/0/ip)
ZONE=$(curl -H "${METADATA_FLAVOR_HEADER}" ${METADATA_URL}/instance/zone | cut -d'/' -f4)
echo "Running in Zone: ${ZONE}, Internal IP: ${INTERNAL_IP}"

# --- Install Packages ---
sudo apt-get update -y
# sudo apt-get upgrade -y # Consider if needed, can increase startup time
sudo apt-get install -y python3 python3-pip git curl wget unzip tree apt-transport-https ca-certificates gnupg

# --- Install Google Cloud CLI (Optional but often useful) ---
# if ! type gcloud > /dev/null; then
#     echo "Installing Google Cloud CLI"

#     curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo tee /usr/share/keyrings/cloud.google.gpg > /dev/null
#     sudo apt-get update -y && sudo apt-get install -y google-cloud-cli
# fi

# --- Application Setup ---
# Install Python dependencies
# cd /path/to/your/cloned/repo
# sudo pip3 install -r requirements.txt

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
# cd src/scripts
pip install -r requirements.txt

# --- Setup Environment Variables ---
# Create .env file from template
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
INDEX_DIR="/data/index"

# Node Identification
HOSTNAME="master-${INTERNAL_IP}"
EOL

# --- Setup Systemd Service ---
sudo tee /etc/systemd/system/crawler-master.service > /dev/null << EOL
[Unit]
Description=Web Crawler Master Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${APP_DIR}/src/scripts
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python3 master_node.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# --- Enable and Start Service ---
sudo systemctl daemon-reload
sudo systemctl enable crawler-master
sudo systemctl start crawler-master

echo "Finished Master Node Bootstrap Script (GCP)"
date '+%Y-%m-%d %H:%M:%S'