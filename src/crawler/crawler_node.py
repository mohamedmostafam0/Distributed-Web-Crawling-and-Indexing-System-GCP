# src/scripts/crawler_node.py

import os
import logging
import time
import json
import uuid
import requests
import socket
import threading
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from urllib.error import URLError
from datetime import datetime
from google.cloud import pubsub_v1, storage
from google.api_core import exceptions
from concurrent.futures import TimeoutError
from dotenv import load_dotenv

load_dotenv()


class CrawlerNode:
    def __init__(self):
        self.hostname = os.environ.get("HOSTNAME", "crawler")
        self._setup_logging()
        self._load_config()
        self._init_clients()

        self.seen_urls = set()
        self.robots_cache = {}  # Cache for robots.txt parsers
        self.REQUESTS_TIMEOUT = 10
        self.POLITE_DELAY = 1
        self.USER_AGENT = "MyDistributedCrawler/1.0 (+http://example.com/botinfo)"


    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - {self.hostname} - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

# --- Configuration ---
    def _load_config(self):
        try:
            self.PROJECT_ID = os.environ["GCP_PROJECT_ID"]
            self.INDEX_QUEUE_TOPIC_ID = os.environ["INDEX_QUEUE_TOPIC_ID"]
            self.NEW_CRAWL_JOB_SUBSCRIPTION_ID = os.environ["NEW_CRAWL_JOB_SUBSCRIPTION_ID"]
            self.NEW_URL_TASKS_TOPIC_ID = os.environ["NEW_URL_TASKS_TOPIC_ID"]
            self.GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
            self.MAX_DEPTH = int(os.environ["MAX_DEPTH"])
            self.HEALTH_METRICS_TOPIC_ID = os.environ["HEALTH_METRICS_TOPIC_ID"]
            self.PROGRESS_METRICS_TOPIC_ID = os.environ["PROGRESS_METRICS_TOPIC_ID"]

        except KeyError as e:
            print(f"Error: Environment variable {e} not set.")
            exit(1)
        except ValueError as e:
            print(f"Error: Environment variable MAX_DEPTH must be an integer: {e}")
            exit(1)


    def _init_clients(self):
        self.subscriber = pubsub_v1.SubscriberClient()
        self.publisher = pubsub_v1.PublisherClient()
        self.storage_client = storage.Client()

        self.subscription_path = self.subscriber.subscription_path(self.PROJECT_ID, self.NEW_CRAWL_JOB_SUBSCRIPTION_ID)
        self.index_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.INDEX_QUEUE_TOPIC_ID)
        self.new_url_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.NEW_URL_TASKS_TOPIC_ID)
        self.health_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.HEALTH_METRICS_TOPIC_ID)
        self.progress_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.PROGRESS_METRICS_TOPIC_ID)


    def publish_health_status(self):
        health_msg = {
            "node_type": "crawler",
            "hostname": socket.gethostname(),
            "status": "online",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.publish_message(self.health_topic_path, health_msg)
        logging.info(f"published health metric")

    def start_health_heartbeat(self):
        def loop():
            while True:
                self.publish_health_status()
                time.sleep(30)
        threading.Thread(target=loop, daemon=True).start()
    

    def normalize_url(self, url):
        """Normalize URL to avoid crawling duplicates."""
        parsed = urlparse(url)
        # Remove fragments, normalize to lowercase
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized.lower().rstrip('/')
        
    def can_fetch(self, url):
        """Check if the crawler is allowed to fetch the URL according to robots.txt rules."""
        parsed_url = urlparse(url)
        robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
        
        # Check if we have a cached parser for this domain
        if robots_url in self.robots_cache:
            return self.robots_cache[robots_url].can_fetch(self.USER_AGENT, url)
        
        # Create a new parser
        rp = RobotFileParser()
        rp.set_url(robots_url)
        
        try:
            logging.info(f"Fetching robots.txt from {robots_url}")
            rp.read()
            # Cache the parser
            self.robots_cache[robots_url] = rp
            allowed = rp.can_fetch(self.USER_AGENT, url)
            if not allowed:
                logging.info(f"Robots.txt disallows crawling: {url}")
            return allowed
        except (URLError, Exception) as e:
            logging.warning(f"Error fetching robots.txt from {robots_url}: {e}")
            # If we can't fetch robots.txt, we'll assume crawling is allowed
            # but we'll cache a permissive parser to avoid repeated attempts
            permissive_parser = RobotFileParser()
            permissive_parser.parse(['User-agent: *', 'Allow: /'])
            self.robots_cache[robots_url] = permissive_parser
            return True
    
    def save_to_gcs(self, bucket_name, blob_path, data, content_type):
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.upload_from_string(data, content_type=content_type)
            return f"gs://{bucket_name}/{blob_path}"
        except Exception as e:
            logging.error(f"Failed to save to GCS path gs://{bucket_name}/{blob_path}: {e}")
            return None
        
    def publish_message(self, topic_path, message_data):
        data = json.dumps(message_data).encode("utf-8")
        try:
            future = self.publisher.publish(topic_path, data)
            future.result(timeout=30)
            logging.debug(f"Published message to {topic_path}: {message_data.get('task_id') or message_data.get('url')}")
            return True
        except exceptions.NotFound:
            logging.error(f"Pub/Sub topic {topic_path} not found.")
            return False
        except Exception as e:
            logging.error(f"Failed to publish message to {topic_path}: {e}")
            return False

    def publish_new_urls_to_master(self, new_urls, domain_restriction, source_task_id, depth):
        if not new_urls:
            return
        new_task_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        gcs_blob_path = f"new_tasks/{new_task_id}_{timestamp}.json"

        message_data = {
            "seed_urls": new_urls,
            "depth": depth,
            "domain_restriction": domain_restriction
        }

        bucket = self.storage_client.bucket(self.GCS_BUCKET_NAME)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_string(json.dumps(message_data), content_type="application/json")
        logging.info(f"Saved new URL batch to gs://{self.GCS_BUCKET_NAME}/{gcs_blob_path}")

        pubsub_msg = {
            "task_id": new_task_id,
            "gcs_path": f"gs://{self.GCS_BUCKET_NAME}/{gcs_blob_path}"
        }

        self.publish_message(self.new_url_topic_path, pubsub_msg)
        logging.info(f"Published new crawl job task_id={new_task_id} to master")


    def publish_crawler_metrics(self, event_type, task_id, url=None, extra=None):
        metrics_message = {
            "node_type": "crawler",
            "task_id": task_id,
            "event": event_type,
            "url": url,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if extra:
            metrics_message.update(extra)
        self.publish_message(self.progress_topic_path, metrics_message)
        logging.info(f"published progress metric")



    def process_crawl_task(self, message: pubsub_v1.subscriber.message.Message):
        """Callback function to handle incoming crawl task messages."""
        try:
            data_str = message.data.decode("utf-8")
            task_data = json.loads(data_str)
            url = task_data.get("url")
            task_id = task_data.get("task_id", "N/A")
            depth = task_data.get("depth", 0)
            depth = int(depth)  # Ensure integer
            depth_limit = task_data.get("depth_limit", self.MAX_DEPTH)
            domain_restriction = task_data.get("domain_restriction")
            source_job_id = task_data.get("source_job_id")

            print(f"🔍 Crawler received: {url} (depth={depth}/{depth_limit})")

            if not url or not url.startswith('http'):
                logging.warning(f"Received invalid task data (missing/invalid URL): {data_str}")
                message.ack()  # Skip invalid
                return
            
            normalized_url = self.normalize_url(url)
            if normalized_url in self.seen_urls:
                logging.info(f"Skipping already seen URL: {normalized_url}")
                message.ack()
                return
            self.seen_urls.add(normalized_url)

            logging.info(f"Received task {task_id}: Crawl URL: {url} at depth {depth}")
            time.sleep(self.POLITE_DELAY)

            if not url or not url.startswith('http'):
                logging.warning(f"Received invalid task data (missing/invalid URL): {data_str}")
                message.ack() # Acknowledge invalid message so it's not redelivered
                return

            # --- Check robots.txt before fetching ---
            if not self.can_fetch(url):
                logging.info(f"Skipping URL due to robots.txt restrictions: {url}")
                message.ack()  # Acknowledge the message as we won't process it
                self.publish_crawler_metrics("url_skipped", task_id=task_id, url=url, extra={"reason": "robots_txt"})
                return
            
            # --- Fetch URL ---
            try:
                headers = {'User-Agent': self.USER_AGENT}
                response = requests.get(url, timeout=self.REQUESTS_TIMEOUT, headers=headers, allow_redirects=True)
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
                gcs_raw_path = self.save_to_gcs(
                    self.GCS_BUCKET_NAME,
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

                # --- Save Processed Text ---
                gcs_processed_path = self.save_to_gcs(
                    self.GCS_BUCKET_NAME,
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
                if not self.publish_message(self.index_topic_path, indexer_message):
                    logging.error(f"Failed to publish index task for {final_url}. Nacking original task.")
                    message.nack() # Let Pub/Sub handle retry
                    return

                self.publish_crawler_metrics("url_crawled", task_id=task_id, url=url)

                # --- Extract and Publish New URLs (if depth allows) ---

                if depth < depth_limit:
                    new_urls_found = 0
                    new_urls = []

                    links = soup.find_all('a', href=True)
                    for link in links:
                        href = link['href']
                        new_url = urljoin(final_url, href)
                        parsed_new_url = urlparse(new_url)

                        if parsed_new_url.scheme in ['http', 'https'] and parsed_new_url.netloc:
                            normalized_new_url = self.normalize_url(new_url)
                            if normalized_new_url in self.seen_urls:
                                continue
                            if domain_restriction and domain_restriction not in parsed_new_url.netloc:
                                continue
                            self.seen_urls.add(normalized_new_url)
                            new_urls.append(normalized_new_url)
                            new_urls_found += 1

                    logging.info(f"Found {new_urls_found} new URLs from {final_url}")
                    # Pass the incremented depth value for the next level of crawling
                    next_depth = depth + 1
                    self.publish_new_urls_to_master(new_urls, domain_restriction, task_id, next_depth)
                    self.publish_crawler_metrics("new_urls_found", task_id=task_id, extra={"task_id": task_id, "count": len(new_urls)})
                    
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
    def run(self):
        logging.info("Crawler node starting...")
        logging.info(f"Project ID: {self.PROJECT_ID}")
        logging.info(f"Listening for tasks on subscription: {self.subscription_path}")
        logging.info(f"Publishing index data to topic: {self.index_topic_path}")
        logging.info(f"Publishing new URLs to topic: {self.new_url_topic_path}")
        logging.info(f"Storing data in GCS Bucket: {self.GCS_BUCKET_NAME}")
        self.start_health_heartbeat()

        # --- Start Subscriber ---
        streaming_pull_future = self.subscriber.subscribe(self.subscription_path, callback=self.process_crawl_task)
        logging.info(f"Listening for messages on {self.subscription_path}...")

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
    node = CrawlerNode()
    node.run()