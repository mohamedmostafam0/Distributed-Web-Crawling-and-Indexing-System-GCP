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
        except KeyError as e:
            logging.error(f"Missing environment variable: {e}")
            exit(1)


# --- Validate Essential Configuration ---
    def _validate_config(self):
        required = {
            "GCP_PROJECT_ID": self.PROJECT_ID,
            "CRAWL_TASKS_TOPIC_ID": self.CRAWL_TASKS_TOPIC_ID,
            "GCS_BUCKET_NAME": self.GCS_BUCKET_NAME,
            "NEW_MASTER_JOB_SUBSCRIPTION_ID": self.NEW_MASTER_JOB_SUBSCRIPTION_ID
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
            self.monitoring_client = monitoring_v3.MetricServiceClient()
            self.crawl_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.CRAWL_TASKS_TOPIC_ID)
            self.subscription_path = self.subscriber.subscription_path(self.PROJECT_ID, self.NEW_MASTER_JOB_SUBSCRIPTION_ID)
        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud clients: {e}", exc_info=True)
            exit(1)

    def publish_health_status(self):
        health_msg = {
            "node_type": "crawler",
            "hostname": socket.gethostname(),
            "status": "online",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.publish_message(metrics_topic_path, health_msg)

    def start_health_heartbeat(self):
        def loop():
            while True:
                self.publish_health_status()
                time.sleep(30)
        threading.Thread(target=loop, daemon=True).start()

    # --- Monitoring Helpers ---
    def publish_metric(metric_name, value):
        series = monitoring_v3.TimeSeries()
        series.metric.type = f"custom.googleapis.com/{metric_name}"
        series.resource.type = "global"
        point = series.points.add()
        point.value.int64_value = value
        point.interval.end_time.seconds = int(time.time())
        point.interval.end_time.nanos = 0

        project_name = f"projects/{PROJECT_ID}"
        self.monitoring_client.create_time_series(request={"name": project_name, "time_series": [series]})


    # Modify publish_crawl_task to accept parameters
    def publish_crawl_task(url, depth=0, domain_restriction=None, source_job_id=None):
        """Publishes a single URL crawl task to Pub/Sub."""
        global total_crawled
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
            future = publisher.publish(self.crawl_topic_path, data)
            total_crawled += 1
            publish_metric("urls_crawled", total_crawled)
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
            total_jobs_received += 1
            self.publish_metric("crawl_jobs_received", self.total_jobs_received)
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
            seed_urls = job_data.get("seed_urls", [])
            depth_limit = job_data.get("depth", 1)
            domain_restriction = job_data.get("domain_restriction")

            if not isinstance(seed_urls, list) or not seed_urls:
                logging.warning(f"No seed URLs found in job {task_id}. Skipping.")
                message.ack()
                return

            for url in seed_urls:
                publish_crawl_task(
                    url,
                    depth=0,
                    domain_restriction=domain_restriction,
                    source_job_id=task_id
                )
                time.sleep(0.05)

            logging.info(f"Published crawl tasks for job {task_id}")
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
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Publishing tasks to Topic: {crawl_topic_path}")
    logging.info(f"Listening for jobs on: {new_job_subscription_path}")
    self.start_health_heartbeat()

    try:
        future = None
        if new_job_subscription_path:
            future = subscriber.subscribe(new_job_subscription_path, callback=handle_new_job)
            logging.info(f"Listening for new crawl job submissions on {new_job_subscription_path}...")

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
    main()