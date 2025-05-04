# src/scripts/indexer_node.py

import os
import logging
import time
import json
from google.cloud import pubsub_v1
from google.cloud import storage
from google.api_core import exceptions
from concurrent.futures import TimeoutError
from elasticsearch import Elasticsearch
from dotenv import load_dotenv
import socket
from datetime import datetime
import threading

load_dotenv()


class IndexerNode:
    def __init__(self):
        self.hostname = os.environ.get("HOSTNAME", "indexer")
        self._setup_logging()
        self._load_config()
        self._init_clients()
        self._init_elasticsearch()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format=f'%(asctime)s - {self.hostname} - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def _load_config(self):
        try:
            self.PROJECT_ID = os.environ["GCP_PROJECT_ID"]
            self.INDEX_QUEUE_SUBSCRIPTION_ID = os.environ["INDEX_QUEUE_SUBSCRIPTION_ID"]
            self.GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
            self.ES_HOST = os.environ["ES_HOST"]
            self.ES_PORT = int(os.environ["ES_PORT"])
            self.ES_USERNAME = os.environ.get("ES_USERNAME")
            self.ES_PASSWORD = os.environ.get("ES_PASSWORD")
            self.ES_INDEX_NAME = os.environ["ES_INDEX_NAME"]
            self.HEALTH_METRICS_TOPIC_ID = os.environ["HEALTH_METRICS_TOPIC_ID"]
            self.PROGRESS_METRICS_TOPIC_ID = os.environ["PROGRESS_METRICS_TOPIC_ID"]

        except KeyError as e:
            print(f"Error: Environment variable {e} not set.")
            exit(1)
        except ValueError as e:
            print(f"Error: Environment variable ES_PORT must be an integer: {e}")
            exit(1)

        logging.info(f"project id is {self.PROJECT_ID}, index queue subscription id is {self.INDEX_QUEUE_SUBSCRIPTION_ID}, "
                     f"gcs bucket name is {self.GCS_BUCKET_NAME}, es host is {self.ES_HOST}, es port is {self.ES_PORT}, "
                     f"es username is {self.ES_USERNAME}, es password is {self.ES_PASSWORD}, es index name is {self.ES_INDEX_NAME}")

    def _init_clients(self):
        self.publisher = pubsub_v1.PublisherClient()  # Add this if not already initialized
        self.subscriber = pubsub_v1.SubscriberClient()
        self.storage_client = storage.Client()
        self.subscription_path = self.subscriber.subscription_path(self.PROJECT_ID, self.INDEX_QUEUE_SUBSCRIPTION_ID)
        self.progress_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.PROGRESS_METRICS_TOPIC_ID)
        self.health_topic_path = self.publisher.topic_path(self.PROJECT_ID, self.HEALTH_METRICS_TOPIC_ID)

    def _init_elasticsearch(self):
        try:
            es_url = f"https://{self.ES_USERNAME}:{self.ES_PASSWORD}@{self.ES_HOST}"
            self.es_client = Elasticsearch(es_url, verify_certs=True)

            if not self.es_client.ping():
                raise ValueError("Elasticsearch connection failed")
            logging.info(f"Connected to Elasticsearch at {self.ES_HOST}:{self.ES_PORT}")

            if not self.es_client.indices.exists(index=self.ES_INDEX_NAME):
                mapping = {
                    "mappings": {
                        "properties": {
                            "url": {"type": "keyword"},
                            "content": {"type": "text", "analyzer": "standard"}
                        }
                    }
                }
                self.es_client.indices.create(index=self.ES_INDEX_NAME, body=mapping)
                logging.info(f"Created Elasticsearch index '{self.ES_INDEX_NAME}'")
        except Exception as e:
            logging.error(f"Failed to initialize Elasticsearch client: {e}", exc_info=True)
            exit(1)

    def publish_health_status(self):
        health_msg = {
            "node_type": "indexer",
            "hostname": socket.gethostname(),
            "status": "online",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.publish_message(self.health_topic_path, health_msg)

    def publish_progress_metric(self, event_type, task_id=None, url=None, extra=None):
        progress_msg = {
            "node_type": "indexer",
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat()
        }
        if task_id:
            progress_msg["task_id"] = task_id
        if url:
            progress_msg["url"] = url
        if extra:
            progress_msg.update(extra)
        self.publish_message(self.progress_topic_path, progress_msg)



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
            return True
        except Exception as e:
            logging.error(f"Failed to publish message to {topic_path}: {e}")
            return False

    def download_from_gcs(self, bucket_name, blob_path):
        try:
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            return blob.download_as_text()
        except exceptions.NotFound:
            logging.error(f"GCS object not found: gs://{bucket_name}/{blob_path}")
            return None
        except Exception as e:
            logging.error(f"Failed to download from GCS path gs://{bucket_name}/{blob_path}: {e}")
            return None

    def index_document(self, url, content):
        try:
            doc = {"url": url, "content": content}
            response = self.es_client.index(index=self.ES_INDEX_NAME, id=url, document=doc)
            result = response.get('result', '')
            if result not in ["created", "updated"]:
                raise Exception(f"Unexpected result from Elasticsearch: {result}")
            logging.info(f"Successfully indexed document ID: {url}")
            return True
        except Exception as e:
            logging.error(f"Error indexing URL {url}: {e}", exc_info=True)
            return False

    def process_indexing_task(self, message: pubsub_v1.subscriber.message.Message):
        try:
            data_str = message.data.decode("utf-8")
            task_data = json.loads(data_str)
            task_id = task_data.get("task_id", "N/A")


            url = task_data.get("final_url") or task_data.get("original_url")
            if not url:
                logging.warning("No URL found in message.")
                message.ack()
                return

            gcs_path = task_data.get("gcs_processed_path")
            content_id = task_data.get("content_id", "N/A")

            if not url or not gcs_path:
                logging.warning(f"Invalid task data (missing URL or GCS path): {data_str}")
                message.ack()
                return

            logging.info(f"Received task: Index content_id {content_id} for URL {url} from {gcs_path}")

            if gcs_path.startswith(f"gs://{self.GCS_BUCKET_NAME}/"):
                blob_path = gcs_path[len(f"gs://{self.GCS_BUCKET_NAME}/"):]
            else:
                logging.error(f"Unexpected GCS path format: {gcs_path}")
                message.ack()
                return

            processed_text = self.download_from_gcs(self.GCS_BUCKET_NAME, blob_path)

            if processed_text is None:
                logging.error(f"Failed to download processed text for {url}. Nacking.")
                message.nack()
                return

            if self.index_document(url, processed_text):
                message.ack()
                logging.info(f"Indexed task for {url}")
                self.publish_progress_metric("url_indexed", task_id=task_data.get("source_task_id"), url=url, extra={"content_id": content_id})

            else:
                message.nack()
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in message: {message.data}")
            message.ack()
        except Exception as e:
            logging.error(f"Unexpected error: {e}", exc_info=True)
            message.nack()

    def run(self):
        logging.info("Indexer node starting...")
        logging.info(f"Project ID: {self.PROJECT_ID}")
        logging.info(f"Listening on: {self.subscription_path}")
        logging.info(f"GCS Bucket: {self.GCS_BUCKET_NAME}")
        logging.info(f"Elasticsearch: {self.ES_HOST}:{self.ES_PORT}, Index: {self.ES_INDEX_NAME}")
        self.start_health_heartbeat()
        streaming_pull_future = self.subscriber.subscribe(self.subscription_path, callback=self.process_indexing_task)
        try:
            streaming_pull_future.result()
        except TimeoutError:
            streaming_pull_future.cancel()
            streaming_pull_future.result()
            logging.info("Subscriber timed out.")
        except KeyboardInterrupt:
            streaming_pull_future.cancel()
            streaming_pull_future.result()
            logging.info("Indexer node shutting down.")
        except Exception as e:
            logging.error(f"Subscriber error: {e}", exc_info=True)
            streaming_pull_future.cancel()
            streaming_pull_future.result()


if __name__ == "__main__":
    node = IndexerNode()
    node.run()
