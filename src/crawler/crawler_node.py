# src/scripts/crawler_node.py

import os
import logging
import time
import json
import uuid
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from google.cloud import pubsub_v1
from google.cloud import storage
from google.api_core import exceptions
from concurrent.futures import TimeoutError
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

import re


# --- Configuration ---
try:
    PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    INDEX_QUEUE_TOPIC_ID = os.environ["INDEX_QUEUE_TOPIC_ID"] # Topic to send data for indexing
    NEW_CRAWL_JOB_SUBSCRIPTION_ID = os.environ["NEW_CRAWL_JOB_SUBSCRIPTION_ID"] # Subscribed to Master's tasks
    NEW_URL_TASKS_TOPIC_ID = os.environ["NEW_URL_TASKS_TOPIC_ID"]

    GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
    MAX_DEPTH = int(os.environ["MAX_DEPTH"])
    
except KeyError as e:
    print(f"Error: Environment variable {e} not set.")
    exit(1)
except ValueError as e:
    print(f"Error: Environment variable MAX_DEPTH must be an integer: {e}")
    exit(1)


# --- Setup Logging ---
# Include instance identifier if running multiple crawlers on one machine (e.g., using HOSTNAME)
hostname = os.environ.get("HOSTNAME", "crawler")
logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - {hostname} - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Initialize Clients ---
subscriber = pubsub_v1.SubscriberClient()
publisher = pubsub_v1.PublisherClient()
storage_client = storage.Client()

subscription_path = subscriber.subscription_path(PROJECT_ID, NEW_CRAWL_JOB_SUBSCRIPTION_ID)
index_topic_path = publisher.topic_path(PROJECT_ID, INDEX_QUEUE_TOPIC_ID)
new_url_topic_path = publisher.topic_path(PROJECT_ID, NEW_URL_TASKS_TOPIC_ID)


# --- Constants ---
REQUESTS_TIMEOUT = 10 # Seconds for HTTP requests
POLITE_DELAY = 1 # Seconds between requests to the same domain (implement proper domain tracking)
USER_AGENT = "MyDistributedCrawler/1.0 (+http://example.com/botinfo)" # Be a good bot!


seen_urls = set()

def normalize_url(url):
    """Normalize URLs to avoid recrawling duplicates (e.g., remove fragments, trailing slashes)."""
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="", path=re.sub(r'/$', '', parsed.path)).geturl()
    return normalized.lower()

# --- Functions ---
def save_to_gcs(bucket_name, blob_path, data, content_type):
    """Saves data to GCS."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        # logging.debug(f"Saved data to gs://{bucket_name}/{blob_path}")
        return f"gs://{bucket_name}/{blob_path}"
    except Exception as e:
        logging.error(f"Failed to save to GCS path gs://{bucket_name}/{blob_path}: {e}")
        return None

def publish_message(topic_path, message_data):
    """Publishes a JSON message to a Pub/Sub topic."""
    data = json.dumps(message_data).encode("utf-8")
    try:
        future = publisher.publish(topic_path, data)
        future.result(timeout=30) # Wait for publish confirmation
        logging.debug(f"Published message to {topic_path}: {message_data.get('task_id') or message_data.get('url')}")
        return True
    except exceptions.NotFound:
        logging.error(f"Pub/Sub topic {topic_path} not found.")
        return False
    except Exception as e:
        logging.error(f"Failed to publish message to {topic_path}: {e}")
        return False

def process_crawl_task(message: pubsub_v1.subscriber.message.Message):
    """Callback function to handle incoming crawl task messages."""
    try:
        data_str = message.data.decode("utf-8")
        task_data = json.loads(data_str)
        url = task_data.get("url")
        task_id = task_data.get("task_id", "N/A")
        depth = task_data.get("depth", 0)
        depth = int(depth)  # Ensure integer
        domain_restriction = task_data.get("domain_restriction")

        if not url or not url.startswith('http'):
            logging.warning(f"Received invalid task data (missing/invalid URL): {data_str}")
            message.ack()  # Skip invalid
            return
        
        normalized_url = normalize_url(url)
        if normalized_url in seen_urls:
            logging.info(f"Skipping already seen URL: {normalized_url}")
            message.ack()
            return
        seen_urls.add(normalized_url)

        if not url or not url.startswith('http'):
            logging.warning(f"Received invalid task data (missing/invalid URL): {data_str}")
            message.ack() # Acknowledge invalid message so it's not redelivered
            return

        logging.info(f"Received task {task_id}: Crawl URL: {url} at depth {depth}")

        # --- Politeness Delay ---
        # TODO: Implement proper tracking of last request time per domain
        time.sleep(POLITE_DELAY)

        # --- Fetch URL ---
        # TODO: Implement robots.txt check before fetching
        try:
            headers = {'User-Agent': USER_AGENT}
            response = requests.get(url, timeout=REQUESTS_TIMEOUT, headers=headers, allow_redirects=True)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            final_url = response.url # URL after redirects
            content_type = response.headers.get('content-type', '').lower()

        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching URL: {url}")
            message.nack() # Let Pub/Sub redeliver later or move to dead-letter
            return
        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for URL: {url} - {e}")
            message.ack() # Acknowledge failed request to avoid infinite retries on permanent errors
            return

        # --- Process Content (if HTML) ---
        if 'html' in content_type:
            html_content = response.text
            content_id = str(uuid.uuid4()) # Unique ID for this content

            # --- Save Raw HTML ---
            gcs_raw_path = save_to_gcs(
                GCS_BUCKET_NAME,
                f"raw_html/{content_id}.html",
                html_content,
                "text/html"
            )
            if not gcs_raw_path:
                message.nack() # Failed to save, retry later
                return

            # --- Parse and Extract ---
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract Text (Basic example: get all text, remove extra whitespace)
            text_content = ' '.join(soup.stripped_strings)
            if not text_content:
                logging.warning(f"No text content extracted from {final_url}")
                # Decide if you still want to index pages with no text
                # message.ack() # Acknowledge if no text is not an error state
                # return

            # --- Save Processed Text ---
            gcs_processed_path = save_to_gcs(
                GCS_BUCKET_NAME,
                f"processed_text/{content_id}.txt",
                text_content,
                "text/plain"
            )
            if not gcs_processed_path:
                message.nack() # Failed to save, retry later
                return

            # --- Publish to Indexer Queue ---
            indexer_message = {
                "source_task_id": task_id,
                "content_id": content_id,
                "original_url": url,
                "final_url": final_url,
                "gcs_processed_path": gcs_processed_path,
                "crawled_timestamp": time.time()
            }
            if not publish_message(index_topic_path, indexer_message):
                 logging.error(f"Failed to publish index task for {final_url}. Nacking original task.")
                 message.nack() # Let Pub/Sub handle retry
                 return

            # --- Extract and Publish New URLs (if depth allows) ---
            if depth < MAX_DEPTH:
                new_urls_found = 0
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    # TODO: Implement better filtering (ignore javascript:, mailto:, fragments, etc.)
                    # TODO: Respect nofollow attributes
                    new_url = urljoin(final_url, href) # Handle relative URLs
                    parsed_new_url = urlparse(new_url)

                    # Basic validation: only crawl http/https, ensure it's a valid structure
                    if parsed_new_url.scheme in ['http', 'https'] and parsed_new_url.netloc:
                        # TODO: Add domain restrictions if needed
                        # TODO: Add check for already seen/crawled URLs to avoid loops/redundancy
                        normalized_new_url = normalize_url(new_url)
                        if normalized_new_url in seen_urls:
                            continue
                        if domain_restriction and domain_restriction not in parsed_new_url.netloc:
                            continue
                        seen_urls.add(normalized_new_url)
                        publish_message(new_url_topic_path, {
                            "url": normalized_new_url,
                            "depth": depth + 1,
                            "domain_restriction": domain_restriction,
                            "source_task_id": task_id
                        })
                        new_urls_found +=1
                logging.info(f"Found and published {new_urls_found} new URLs from {final_url}")

            logging.info(f"Successfully processed and queued for indexing: {final_url}")
            message.ack() # Acknowledge the original task message ONLY after success

        else:
            # Handle non-HTML content if needed (e.g., save PDFs, images)
            logging.info(f"Skipping non-HTML content type '{content_type}' for URL: {url}")
            message.ack() # Acknowledge non-HTML task as completed

    except json.JSONDecodeError:
        logging.error(f"Failed to decode message data: {message.data}")
        message.ack() # Cannot process, discard message
    except Exception as e:
        logging.error(f"Unexpected error processing message for task {task_id}: {e}", exc_info=True)
        message.nack() # Unexpected error, let Pub/Sub redeliver

# --- Main Execution ---
def main():
    logging.info("Crawler node starting...")
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Listening for tasks on subscription: {subscription_path}")
    logging.info(f"Publishing index data to topic: {index_topic_path}")
    logging.info(f"Publishing new URLs to topic: {new_url_topic_path}")
    logging.info(f"Storing data in GCS Bucket: {GCS_BUCKET_NAME}")
    logging.info(f"Max Crawl Depth: {MAX_DEPTH}")

    # --- Start Subscriber ---
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_crawl_task)
    logging.info(f"Listening for messages on {subscription_path}...")

    # Keep the main thread alive, otherwise the background subscriber thread dies.
    try:
        # Wait indefinitely for messages, stopping on Ctrl+C or other termination signals
        # Add a timeout if you want the subscriber to stop after a period of inactivity
        streaming_pull_future.result()
    except TimeoutError:
        streaming_pull_future.cancel()
        streaming_pull_future.result() # Block until the shutdown is complete
        logging.info("Subscriber timed out.")
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        streaming_pull_future.result() # Wait for graceful shutdown
        logging.info("Crawler node shutting down.")
    except Exception as e:
        logging.error(f"Subscriber error: {e}", exc_info=True)
        streaming_pull_future.cancel()
        streaming_pull_future.result()

if __name__ == "__main__":
    main()