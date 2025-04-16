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
load_dotenv()

# --- Configuration ---
try:
    PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    INDEX_QUEUE_SUBSCRIPTION_ID = os.environ["INDEX_QUEUE_SUBSCRIPTION_ID"]
    GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
    ES_HOST = os.environ.get("ES_HOST", "localhost")
    ES_PORT = int(os.environ.get("ES_PORT", "9200"))
    ES_INDEX_NAME = os.environ.get("ES_INDEX_NAME", "webcrawler_index")
except KeyError as e:
    print(f"Error: Environment variable {e} not set.")
    exit(1)
except ValueError as e:
    print(f"Error: Environment variable ES_PORT must be an integer: {e}")
    exit(1)

# --- Setup Logging ---
hostname = os.environ.get("HOSTNAME", "indexer")
logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - {hostname} - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- Initialize Clients ---
subscriber = pubsub_v1.SubscriberClient()
storage_client = storage.Client()
subscription_path = subscriber.subscription_path(PROJECT_ID, INDEX_QUEUE_SUBSCRIPTION_ID)

# --- Initialize Elasticsearch ---
try:
    es_client = Elasticsearch(
        [{"host": ES_HOST, "port": ES_PORT, "scheme": "http"}]
    )
    if not es_client.ping():
        raise ValueError("Elasticsearch connection failed")
    logging.info(f"Connected to Elasticsearch at {ES_HOST}:{ES_PORT}")

    if not es_client.indices.exists(index=ES_INDEX_NAME):
        mapping = {
            "mappings": {
                "properties": {
                    "url": {"type": "keyword"},
                    "content": {"type": "text", "analyzer": "standard"}
                }
            }
        }
        es_client.indices.create(index=ES_INDEX_NAME, body=mapping)
        logging.info(f"Created Elasticsearch index '{ES_INDEX_NAME}'")
except Exception as e:
    logging.error(f"Failed to initialize Elasticsearch client: {e}", exc_info=True)
    exit(1)

# --- Download Text from GCS ---
def download_from_gcs(bucket_name, blob_path):
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        return blob.download_as_text()
    except exceptions.NotFound:
        logging.error(f"GCS object not found: gs://{bucket_name}/{blob_path}")
        return None
    except Exception as e:
        logging.error(f"Failed to download from GCS path gs://{bucket_name}/{blob_path}: {e}")
        return None

# --- Indexing Function ---
def index_document(url, content):
    try:
        doc = {"url": url, "content": content}
        response = es_client.index(index=ES_INDEX_NAME, id=url, document=doc)
        result = response.get('result', '')
        if result not in ["created", "updated"]:
            raise Exception(f"Unexpected result from Elasticsearch: {result}")
        logging.info(f"Successfully indexed document ID: {url}")
        return True
    except Exception as e:
        logging.error(f"Error indexing URL {url}: {e}", exc_info=True)
        return False

# --- Message Callback ---
def process_indexing_task(message: pubsub_v1.subscriber.message.Message):
    try:
        data_str = message.data.decode("utf-8")
        task_data = json.loads(data_str)

        url = task_data.get("final_url") or task_data.get("original_url")
        gcs_path = task_data.get("gcs_processed_path")
        content_id = task_data.get("content_id", "N/A")

        if not url or not gcs_path:
            logging.warning(f"Invalid task data (missing URL or GCS path): {data_str}")
            message.ack()
            return

        logging.info(f"Received task: Index content_id {content_id} for URL {url} from {gcs_path}")

        if gcs_path.startswith(f"gs://{GCS_BUCKET_NAME}/"):
            blob_path = gcs_path[len(f"gs://{GCS_BUCKET_NAME}/"):]
        else:
            logging.error(f"Unexpected GCS path format: {gcs_path}")
            message.ack()
            return

        processed_text = download_from_gcs(GCS_BUCKET_NAME, blob_path)

        if processed_text is None:
            logging.error(f"Failed to download processed text for {url}. Nacking.")
            message.nack()
            return

        if index_document(url, processed_text):
            message.ack()
            logging.info(f"Indexed task for {url}")
        else:
            message.nack()
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in message: {message.data}")
        message.ack()
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        message.nack()

# --- Main ---
def main():
    logging.info("Indexer node starting...")
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Listening on: {subscription_path}")
    logging.info(f"GCS Bucket: {GCS_BUCKET_NAME}")
    logging.info(f"Elasticsearch: {ES_HOST}:{ES_PORT}, Index: {ES_INDEX_NAME}")

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_indexing_task)
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
    main()
