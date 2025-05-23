# src/scripts/master_node.py

import os
import logging
import time
import json
import uuid
import socket
import threading
from datetime import datetime
from google.cloud import pubsub_v1, storage, monitoring_v3
from google.api_core import exceptions
from dotenv import load_dotenv

load_dotenv()
# --- Configuration ---


class MasterNode:
    def __init__(self):
        self._setup_logging()
        self._load_config()
        self._validate_config()
        self._init_clients()
        self.total_crawled = 0
        self.total_jobs_received = 0

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - Master - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def _load_config(self):
        try:
            self.PROJECT_ID = os.environ["GCP_PROJECT_ID"]
            self.CRAWL_TASKS_TOPIC_ID = os.environ["CRAWL_TASKS_TOPIC_ID"]
            self.GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
            self.NEW_MASTER_JOB_SUBSCRIPTION_ID = os.environ["NEW_MASTER_JOB_SUBSCRIPTION_ID"]
            self.METRICS_TOPIC_ID = os.environ["METRICS_TOPIC_ID"]
            self.HEALTH_METRICS_TOPIC_ID = os.environ["HEALTH_METRICS_TOPIC_ID"]
            self.PROGRESS_METRICS_TOPIC_ID = os.environ["PROGRESS_METRICS_TOPIC_ID"]

        except KeyError as e:
            logging.error(f"Missing environment variable: {e}")
            exit(1)


# --- Validate Essential Configuration ---
    def _validate_config(self):
        required = {
            "GCP_PROJECT_ID": self.PROJECT_ID,
            "CRAWL_TASKS_TOPIC_ID": self.CRAWL_TASKS_TOPIC_ID,
            "GCS_BUCKET_NAME": self.GCS_BUCKET_NAME,
            "NEW_MASTER_JOB_SUBSCRIPTION_ID": self.NEW_MASTER_JOB_SUBSCRIPTION_ID,
            "METRICS_TOPIC_ID": self.METRICS_TOPIC_ID
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            logging.error(f"Missing essential environment variables: {', '.join(missing)}")
            exit(1)


# --- Initialize Clients ---
    def _init_clients(self):
        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.subscriber = pubsub_v1.SubscriberClient()
            self.storage_client = storage.Client()
            self.crawl_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.CRAWL_TASKS_TOPIC_ID)
            self.subscription_path = self.subscriber.subscription_path(self.PROJECT_ID, self.NEW_MASTER_JOB_SUBSCRIPTION_ID)
            self.metrics_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.METRICS_TOPIC_ID)
            self.health_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.HEALTH_METRICS_TOPIC_ID)
            self.progress_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.PROGRESS_METRICS_TOPIC_ID)

        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud clients: {e}", exc_info=True)
            exit(1)

    def publish_health_status(self):
        health_msg = {
            "node_type": "master",
            "hostname": socket.gethostname(),
            "status": "online",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.publish_message(self.health_topic_path, health_msg)

    def publish_progress_metric(self, event_type, extra=None):
        message = {
            "node_type": "master",
            "event": event_type,
            "hostname": socket.gethostname(),
            "timestamp": datetime.utcnow().isoformat()
        }
        if extra:
            message.update(extra)
        self.publish_message(self.progress_topic_path, message)

    def start_health_heartbeat(self):
        def loop():
            while True:
                self.publish_health_status()
                time.sleep(30)
        threading.Thread(target=loop, daemon=True).start()

    def publish_message(self, topic_path, message_data):
        data = json.dumps(message_data).encode("utf-8")
        try:
            future = self.publisher.publish(topic_path, data)
            future.result(timeout=30)
            logging.debug(f"Published message to {topic_path}: {message_data}")
            return True
        except exceptions.NotFound:
            logging.error(f"Pub/Sub topic {topic_path} not found.")
            return False
        except Exception as e:
            logging.error(f"Failed to publish message to {topic_path}: {e}")
            return False

    # Modify publish_crawl_task to accept parameters
    def publish_crawl_task(self, url, depth=0, domain_restriction=None, source_job_id=None, depth_limit=None, is_continuation=False):
        """Publishes a single URL crawl task to Pub/Sub."""
        # If this is a continuation, use the source_job_id as the task_id to maintain the same task lineage
        # Otherwise, generate a new UUID for the task
        task_id = source_job_id if is_continuation else str(uuid.uuid4())
        message_data = {
            "task_id": task_id,
            "url": url,
            "depth": depth,
            "depth_limit": depth_limit,
            "domain_restriction": domain_restriction, # Pass along
            "source_job_id": source_job_id, # Optional: Link back to UI job
            "is_continuation": is_continuation # Flag to indicate if this is a continuation of an existing task
        }
        data = json.dumps(message_data).encode("utf-8")

        try:
            future = self.publisher.publish(self.crawl_topic_path, data)
            self.total_crawled += 1
            # self.publish_metric("urls_crawled", self.total_crawled)
            future.result(timeout=30)
            logging.info(f"Published task {task_id} for URL: {url} (From Job: {source_job_id}, Depth: {depth}, Domain: {domain_restriction})")
            return True
        except exceptions.GoogleAPICallError as e:
            logging.error(f"API error publishing task for URL {url}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error publishing task for URL {url}: {e}", exc_info=True)
            return False


    # --- Handle Incoming Crawl Job Requests ---
    def handle_new_job(self, message: pubsub_v1.subscriber.message.Message):
        global total_jobs_received
        try:
            data_str = message.data.decode("utf-8").strip()
            if not data_str:
                logging.error("Received empty message from Pub/Sub.")
                message.ack()
                return
            try:
                job_meta = json.loads(data_str)
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse JSON: {e}")
                message.ack()
                return

            task_id = job_meta.get("task_id")
            gcs_path = job_meta.get("gcs_path")
            is_continuation = job_meta.get("is_continuation", False)
            
            # Only count as a new job and publish job_received event if this is not a continuation
            if not is_continuation:
                self.total_jobs_received += 1
                # self.publish_metric("crawl_jobs_received", self.total_jobs_received)
                self.publish_progress_metric("job_received", extra={"job_id": task_id})
            else:
                # For continuations, publish a different event type to avoid UI clutter
                url_count = job_meta.get("url_count", 0)
                logging.info(f"Received continuation of task {task_id} with {url_count} new URLs")
                self.publish_progress_metric("task_continuation", extra={"job_id": task_id, "url_count": url_count})

            if not task_id or not gcs_path:
                logging.error("Missing task_id or gcs_path in the message.")
                message.ack()
                return

            logging.info(f"Received task {task_id} from {gcs_path}")

            if not gcs_path.startswith("gs://"):
                logging.error(f"Invalid GCS path: {gcs_path}")
                message.ack()
                return

            # Safe split: remove 'gs://' and split at first slash
            try:
                parts = gcs_path[5:].split("/", 1)
                bucket_name, blob_path = parts
            except ValueError:
                logging.error(f"Failed to parse GCS path: {gcs_path}")
                message.ack()
                return

            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            blob_content = blob.download_as_text()
            if not blob_content.strip():
                logging.error(f"GCS blob at {gcs_path} is empty.")
                message.ack()
                return

            job_data = json.loads(blob_content)
            
            # Check if this is a batch of URLs from crawler or a seed job from UI
            if "urls" in job_data:
                # This is a batch of URLs from crawler
                urls = job_data.get("urls", [])
                depth = job_data.get("depth")
                domain_restriction = job_data.get("domain_restriction")
                source_task_id = job_data.get("source_task_id")
                url_count = job_data.get("url_count", len(urls))
                
                if not isinstance(urls, list) or not urls:
                    logging.warning(f"No URLs found in batch {task_id}. Skipping.")
                    message.ack()
                    return
                
                logging.info(f"Processing batch of {url_count} URLs from task {task_id}")
                
                # Process URLs in the batch
                # Important: Use the original task_id for all URLs in the batch
                # This ensures all URLs found under a seed URL are attached to the same task
                for url in urls:
                    # For continuations, use the original depth_limit if available, otherwise use MAX_DEPTH
                    original_depth_limit = job_data.get("depth_limit", job_data.get("total_depth", 3))
                    
                    self.publish_crawl_task(
                        url,
                        depth=depth,
                        domain_restriction=domain_restriction,
                        source_job_id=task_id,  # Use the task_id from the batch, not source_task_id
                        depth_limit=original_depth_limit,  # Use the original depth limit
                        is_continuation=True  # Flag to indicate this is a continuation
                    )
                    time.sleep(0.01)  # Small delay to avoid overwhelming the system
                
                self.publish_progress_metric("urls_scheduled", extra={"count": url_count, "job_id": task_id})
                logging.info(f"Published {url_count} crawl tasks for batch {task_id}")
                message.ack()
            else:
                # This is a seed job from UI
                seed_urls = job_data.get("seed_urls", [])
                depth_limit = job_data.get("depth")
                domain_restriction = job_data.get("domain_restriction")

                if not isinstance(seed_urls, list) or not seed_urls:
                    logging.warning(f"No seed URLs found in job {task_id}. Skipping.")
                    message.ack()
                    return

                for url in seed_urls:
                    self.publish_crawl_task(
                        url,
                        depth=0,
                        domain_restriction=domain_restriction,
                        source_job_id=task_id,
                        depth_limit=depth_limit
                    )
                    time.sleep(0.05)
                self.publish_progress_metric("url_scheduled", extra={"url": seed_urls[0], "job_id": task_id})
                logging.info(f"Published seed crawl tasks for job {task_id}")
                message.ack()

        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON: {e}")
            message.ack()
        except Exception as e:
            logging.error(f"Failed to process incoming crawl job: {e}", exc_info=True)
            message.nack()



# --- Main Execution ---
    def run(self):
        logging.info("Master node starting...")
        logging.info(f"Project ID: {self.PROJECT_ID}")
        logging.info(f"Publishing tasks to Topic: {self.crawl_topic_path}")
        logging.info(f"Listening for jobs on: {self.subscription_path}")
        self.start_health_heartbeat()

        try:
            future = None
            if self.subscription_path:
                future = self.subscriber.subscribe(self.subscription_path, callback=self.handle_new_job)
                logging.info(f"Listening for new crawl job submissions on {self.subscription_path}...")

                # Keep the process running
                future.result()
            else:
                logging.warning("No subscription path provided. Master node will not subscribe to any jobs.")

        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received. Shutting down gracefully...")
            if future:
                future.cancel()
                future.result()
            logging.info("Master node shut down successfully.")

        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}", exc_info=True)
            if future:
                future.cancel()
                future.result()



if __name__ == "__main__":
    node = MasterNode()
    node.run()