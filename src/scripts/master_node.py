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
    NEW_CRAWL_JOB_SUBSCRIPTION_ID = os.environ.get("NEW_CRAWL_JOB_SUBSCRIPTION_ID")

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
    "NEW_CRAWL_JOB_SUBSCRIPTION_ID": NEW_CRAWL_JOB_SUBSCRIPTION_ID
}


missing_vars = [k for k, v in essential_vars.items() if v is None]
if missing_vars:
    logging.error(f"Error: Missing essential environment variables: {', '.join(missing_vars)}")
    logging.error("Please set them in your environment or a .env file.")
    exit(1)

# --- Initialize Clients ---
try:
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient() # Add subscriber
    storage_client = storage.Client()
    crawl_topic_path = publisher.topic_path(PROJECT_ID, CRAWL_TASKS_TOPIC_ID)
    # --- NEW: Subscription Path ---
    new_job_subscription_path = None
    if NEW_CRAWL_JOB_SUBSCRIPTION_ID:
        new_job_subscription_path = subscriber.subscription_path(
            PROJECT_ID, NEW_CRAWL_JOB_SUBSCRIPTION_ID
        )
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

# Modify publish_crawl_task to accept parameters
def publish_crawl_task(url, depth=0, domain_restriction=None, source_job_id=None):
    """Publishes a single URL crawl task to Pub/Sub."""
    task_id = str(uuid.uuid4())
    message_data = {
        "task_id": task_id,
        "url": url,
        "depth": depth,
        "domain_restriction": domain_restriction, # Pass along
        "source_job_id": source_job_id # Optional: Link back to UI job
    }
    data = json.dumps(message_data).encode("utf-8")
    try:
        future = publisher.publish(crawl_topic_path, data)
        message_id = future.result(timeout=30)
        logging.info(f"Published task {task_id} for URL: {url} (From Job: {source_job_id}, Depth: {depth}, Domain: {domain_restriction})")
        return True
    except exceptions.NotFound:
        logging.error(f"Pub/Sub topic {crawl_topic_path} not found.")
        return False
    except Exception as e:
        logging.error(f"Error publishing task for URL {url}: {e}", exc_info=True)
        return False


# --- NEW: Callback for UI Job Submissions ---
def new_job_callback(message: pubsub_v1.subscriber.message.Message):
    """Processes new crawl job requests received from the UI."""
    job_submission_id = message.message_id # Use Pub/Sub message ID as job ref
    logging.info(f"Received new crawl job submission: {job_submission_id}")
    try:
        data_str = message.data.decode("utf-8")
        job_data = json.loads(data_str)

        seed_urls = job_data.get("seed_urls", [])
        depth_limit = job_data.get("depth_limit", 0) # Use submitted depth
        domain_restriction = job_data.get("domain_restriction")

        if not isinstance(seed_urls, list) or not seed_urls:
             logging.warning(f"Job {job_submission_id} has no valid seed URLs. Skipping.")
             message.ack()
             return

        logging.info(f"Processing job {job_submission_id}: {len(seed_urls)} seeds, depth={depth_limit}, domain={domain_restriction}")

        success_count = 0
        for url in seed_urls:
            if publish_crawl_task(
                url,
                depth=0, # Start UI submitted jobs at depth 0 relative to *their* seeds
                domain_restriction=domain_restriction,
                source_job_id=job_submission_id
            ):
                success_count += 1
            time.sleep(0.01) # Small delay between publishes

        logging.info(f"Finished publishing {success_count}/{len(seed_urls)} tasks for job {job_submission_id}.")
        message.ack() # Acknowledge the job submission message

    except json.JSONDecodeError:
        logging.error(f"Failed to decode job submission message data: {message.data}")
        message.ack() # Discard malformed message
    except Exception as e:
        logging.error(f"Error processing job submission {job_submission_id}: {e}", exc_info=True)
        message.nack() # Error processing, let Pub/Sub redeliver



# --- Main Execution ---
def main():
    logging.info("Master node starting...")
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Publishing tasks to Topic: {crawl_topic_path}")
    logging.info(f"Reading seeds from Bucket: {GCS_BUCKET_NAME}, Path: {SEED_FILE_PATH}")

    seed_urls = read_seed_urls_from_gcs(GCS_BUCKET_NAME, SEED_FILE_PATH)

    # --- Initial Seed Publishing (Optional) ---
    seed_urls = read_seed_urls_from_gcs(GCS_BUCKET_NAME, SEED_FILE_PATH)
    if seed_urls:
        published_count = 0
        for url in seed_urls:
            # Publish initial seeds with default params maybe
            if publish_crawl_task(url, depth=0, source_job_id="initial_gcs_seed"):
                published_count += 1
            time.sleep(0.05)
        logging.info(f"Finished publishing {published_count}/{len(seed_urls)} initial GCS seed tasks.")
    else:
        logging.warning("No initial seed URLs found in GCS.")


    # --- Start Subscriber for UI Jobs ---
    subscriber_future = None
    if new_job_subscription_path:
        subscriber_future = subscriber.subscribe(new_job_subscription_path, callback=new_job_callback)
        logging.info(f"Listening for new crawl job submissions on {new_job_subscription_path}...")
        try:
             # Keep the script alive waiting for UI jobs
             # The .result() call blocks indefinitely until an error or shutdown.
             subscriber_future.result()
        except TimeoutError:
             subscriber_future.cancel()
             subscriber_future.result() # Block until shutdown completes
             logging.info("UI Job Subscriber timed out (if timeout was set).")
        except KeyboardInterrupt:
             subscriber_future.cancel()
             subscriber_future.result() # Wait for graceful shutdown
             logging.info("Master node shutting down.")
        except Exception as e:
             logging.error(f"UI Job Subscriber error: {e}", exc_info=True)
             subscriber_future.cancel()
             subscriber_future.result()
    else:
        # If no UI job subscription, maybe just run indefinitely or exit after seeding
        logging.info("No UI job subscription configured. Master node will exit after initial seeding (or run idly).")
        # You might add a `while True: time.sleep(60)` here if needed for other tasks.


if __name__ == "__main__":
    main()