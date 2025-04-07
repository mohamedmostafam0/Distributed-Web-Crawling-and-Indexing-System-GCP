# src/scripts/master_node.py

import os
import logging
import time
import json
import uuid
from google.cloud import pubsub_v1
from google.cloud import storage
from google.api_core import exceptions
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

# --- Configuration ---
try:
    PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    CRAWL_TASKS_TOPIC_ID = os.environ["CRAWL_TASKS_TOPIC_ID"] # Topic to send URLs to crawlers
    GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
    SEED_FILE_PATH = os.environ.get("SEED_FILE_PATH", "seeds/start_urls.txt") # Path within GCS bucket
except KeyError as e:
    print(f"Error: Environment variable {e} not set.")
    exit(1)

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Master - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Validate Essential Configuration ---
essential_vars = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "CRAWL_TASKS_TOPIC_ID": CRAWL_TASKS_TOPIC_ID,
    "GCS_BUCKET_NAME": GCS_BUCKET_NAME,
}


missing_vars = [k for k, v in essential_vars.items() if v is None]
if missing_vars:
    logging.error(f"Error: Missing essential environment variables: {', '.join(missing_vars)}")
    logging.error("Please set them in your environment or a .env file.")
    exit(1)

# --- Initialize Clients ---
try:
    publisher = pubsub_v1.PublisherClient()
    storage_client = storage.Client()
    topic_path = publisher.topic_path(PROJECT_ID, CRAWL_TASKS_TOPIC_ID)
except Exception as e:
    logging.error(f"Failed to initialize Google Cloud clients: {e}", exc_info=True)
    exit(1)


# --- Functions ---
def read_seed_urls_from_gcs(bucket_name, file_path):
    """Reads seed URLs from a file in GCS."""
    urls = []
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        logging.info(f"Attempting to read seed URLs from gs://{bucket_name}/{file_path}")
        seed_content = blob.download_as_text()
        urls = [url.strip() for url in seed_content.splitlines() if url.strip() and url.startswith('http')]
        logging.info(f"Successfully read {len(urls)} seed URLs.")
    except exceptions.NotFound:
        logging.error(f"Seed file not found at gs://{bucket_name}/{file_path}")
    except Exception as e:
        logging.error(f"Error reading seed URLs from GCS: {e}", exc_info=True)
    return urls

def publish_crawl_task(url, depth=0):
    """Publishes a single URL crawl task to Pub/Sub."""
    task_id = str(uuid.uuid4())
    message_data = {
        "task_id": task_id,
        "url": url,
        "depth": depth,
        # Add any other relevant parameters here (e.g., domain restrictions)
    }
    # Data must be a bytestring
    data = json.dumps(message_data).encode("utf-8")
    try:
        # When you publish a message, the client returns a future.
        future = publisher.publish(topic_path, data)
        message_id = future.result() # Wait for publish confirmation
        logging.info(f"Published task {task_id} for URL: {url} (Message ID: {message_id})")
        return True
    except exceptions.NotFound:
        logging.error(f"Pub/Sub topic {topic_path} not found.")
        return False
    except Exception as e:
        logging.error(f"Error publishing task for URL {url}: {e}", exc_info=True)
        return False

# --- Main Execution ---
def main():
    logging.info("Master node starting...")
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Publishing tasks to Topic: {topic_path}")
    logging.info(f"Reading seeds from Bucket: {GCS_BUCKET_NAME}, Path: {SEED_FILE_PATH}")

    seed_urls = read_seed_urls_from_gcs(GCS_BUCKET_NAME, SEED_FILE_PATH)

    if not seed_urls:
        logging.warning("No seed URLs found or read. Exiting.")
        return

    published_count = 0
    for url in seed_urls:
        if publish_crawl_task(url, depth=0): # Start seeds at depth 0
             published_count += 1
        time.sleep(0.05) # Small delay to avoid hitting limits quickly

    logging.info(f"Finished publishing {published_count}/{len(seed_urls)} initial seed tasks.")
    logging.info("Master node initialization complete. Running indefinitely (or until stopped).")

    # Keep the master running (e.g., to potentially handle status updates or add more URLs later)
    # In a real deployment, this might be managed by systemd or similar.
    try:
        while True:
            # TODO: Implement optional status monitoring or dynamic URL adding if needed
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Master node shutting down.")

if __name__ == "__main__":
    main()