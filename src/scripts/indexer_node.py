# src/scripts/indexer_node.py

import os
import logging
import time
import json
from google.cloud import pubsub_v1
from google.cloud import storage
from google.api_core import exceptions
from concurrent.futures import TimeoutError
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

# --- !!! Placeholder for your chosen Indexing Library !!! ---
# Example using Whoosh (requires pip install Whoosh)
# from whoosh.index import create_in, open_dir
# from whoosh.fields import Schema, TEXT, ID
# from whoosh.qparser import QueryParser

# Example using Elasticsearch (requires pip install elasticsearch)
# from elasticsearch import Elasticsearch

# --- Configuration ---
try:
    PROJECT_ID = os.environ["GCP_PROJECT_ID"]
    INDEX_QUEUE_SUBSCRIPTION_ID = os.environ["INDEX_QUEUE_SUBSCRIPTION_ID"] # Subscribed to Crawler's output
    GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
    # For Whoosh: Directory where the index is stored (needs to be on persistent disk)
    INDEX_DIR = os.environ.get("INDEX_DIR", "/data/index") # Ensure this path exists and is writable
    # For Elasticsearch: Connection details
    # ES_HOST = os.environ.get("ES_HOST", "localhost")
    # ES_PORT = int(os.environ.get("ES_PORT", "9200"))
    # ES_INDEX_NAME = os.environ.get("ES_INDEX_NAME", "webcrawler_index")
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

# --- !!! Initialize Index !!! ---
# This part is highly dependent on your chosen indexing library

# --- Example: Whoosh Initialization ---
# Define the schema for the index
# schema = Schema(
#     url=ID(stored=True, unique=True), # Store URL, make it unique
#     content=TEXT(stored=False, analyzer=analysis.StemmingAnalyzer()) # Index content, use stemming
# )
#
# index = None
# if not os.path.exists(INDEX_DIR):
#     os.makedirs(INDEX_DIR)
#     index = create_in(INDEX_DIR, schema)
#     logging.info(f"Created new Whoosh index at {INDEX_DIR}")
# else:
#     try:
#         index = open_dir(INDEX_DIR)
#         logging.info(f"Opened existing Whoosh index at {INDEX_DIR}")
#     except Exception as e:
#         logging.error(f"Failed to open Whoosh index at {INDEX_DIR}: {e}", exc_info=True)
#         exit(1) # Cannot proceed without index
# --- End Whoosh Example ---

# --- Example: Elasticsearch Initialization ---
# try:
#     es_client = Elasticsearch(
#         [{'host': ES_HOST, 'port': ES_PORT, 'scheme': 'http'}], # Use https if applicable
#         # Add authentication if needed: http_auth=('user', 'secret')
#     )
#     # Check connection
#     if not es_client.ping():
#         raise ValueError("Elasticsearch connection failed")
#     logging.info(f"Connected to Elasticsearch at {ES_HOST}:{ES_PORT}")
#
#     # Create index if it doesn't exist (basic mapping example)
#     if not es_client.indices.exists(index=ES_INDEX_NAME):
#         mapping = {
#             "properties": {
#                 "url": {"type": "keyword"}, # Use keyword for exact match URLs
#                 "content": {"type": "text", "analyzer": "standard"} # Use text for full-text search
#             }
#         }
#         es_client.indices.create(index=ES_INDEX_NAME, mappings=mapping)
#         logging.info(f"Created Elasticsearch index '{ES_INDEX_NAME}'")
#
# except Exception as e:
#     logging.error(f"Failed to initialize Elasticsearch client: {e}", exc_info=True)
#     exit(1) # Cannot proceed without Elasticsearch connection
# --- End Elasticsearch Example ---

logging.warning("INDEXING LOGIC IS USING PLACEHOLDERS! Implement actual indexing.")

# --- Functions ---
def download_from_gcs(bucket_name, blob_path):
    """Downloads text data from GCS."""
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        data = blob.download_as_text()
        # logging.debug(f"Downloaded data from gs://{bucket_name}/{blob_path}")
        return data
    except exceptions.NotFound:
        logging.error(f"GCS object not found: gs://{bucket_name}/{blob_path}")
        return None
    except Exception as e:
        logging.error(f"Failed to download from GCS path gs://{bucket_name}/{blob_path}: {e}")
        return None

def index_document(url, content):
    """Placeholder function to index the document using the chosen library."""
    logging.info(f"Attempting to index URL: {url} (Content length: {len(content)})")
    try:
        # --- !!! Replace with actual indexing logic !!! ---

        # --- Whoosh Example ---
        # writer = index.writer()
        # # Use update_document to handle potential duplicates based on the unique 'url' field
        # writer.update_document(url=url, content=content)
        # writer.commit()
        # logging.info(f"Successfully indexed/updated document for URL: {url} in Whoosh")
        # --- End Whoosh Example ---

        # --- Elasticsearch Example ---
        # doc_id = url # Use URL as document ID (or generate one)
        # doc = {
        #     'url': url,
        #     'content': content
        # }
        # response = es_client.index(index=ES_INDEX_NAME, id=doc_id, document=doc)
        # if response.get('result') not in ['created', 'updated']:
        #       raise Exception(f"Elasticsearch indexing failed: {response}")
        # logging.info(f"Successfully indexed document ID {doc_id} to Elasticsearch index '{ES_INDEX_NAME}'")
        # --- End Elasticsearch Example ---

        # Simulate indexing work
        time.sleep(0.1)
        logging.info(f"PLACEHOLDER: Successfully indexed document for URL: {url}")
        return True

    except Exception as e:
        logging.error(f"Failed to index document for URL {url}: {e}", exc_info=True)
        return False


def process_indexing_task(message: pubsub_v1.subscriber.message.Message):
    """Callback function to handle incoming indexing task messages."""
    try:
        data_str = message.data.decode("utf-8")
        task_data = json.loads(data_str)

        url = task_data.get("final_url") or task_data.get("original_url")
        gcs_path = task_data.get("gcs_processed_path")
        content_id = task_data.get("content_id", "N/A")

        if not url or not gcs_path:
            logging.warning(f"Received invalid task data (missing URL or GCS path): {data_str}")
            message.ack() # Discard invalid message
            return

        logging.info(f"Received task: Index content_id {content_id} for URL {url} from {gcs_path}")

        # --- Download Processed Text ---
        # GCS paths look like gs://bucket-name/path/to/blob
        # We only need the path part for the blob object
        if gcs_path.startswith(f"gs://{GCS_BUCKET_NAME}/"):
             blob_path = gcs_path[len(f"gs://{GCS_BUCKET_NAME}/"):]
        else:
             logging.error(f"Received GCS path with unexpected format: {gcs_path}")
             message.ack() # Discard if format is wrong
             return

        processed_text = download_from_gcs(GCS_BUCKET_NAME, blob_path)

        if processed_text is None:
            logging.error(f"Failed to download processed text for {url} from {gcs_path}. Nacking.")
            message.nack() # Let Pub/Sub redeliver later
            return

        # --- Perform Indexing ---
        if index_document(url, processed_text):
            # Indexing successful
            message.ack()
            logging.info(f"Successfully processed and indexed task for {url}")
        else:
            # Indexing failed
            logging.error(f"Failed to index task for {url}. Nacking.")
            message.nack() # Let Pub/Sub redeliver later

    except json.JSONDecodeError:
        logging.error(f"Failed to decode message data: {message.data}")
        message.ack() # Cannot process, discard message
    except Exception as e:
        logging.error(f"Unexpected error processing indexing message: {e}", exc_info=True)
        message.nack() # Unexpected error, let Pub/Sub redeliver

# --- Main Execution ---
def main():
    logging.info("Indexer node starting...")
    logging.info(f"Project ID: {PROJECT_ID}")
    logging.info(f"Listening for tasks on subscription: {subscription_path}")
    logging.info(f"Using GCS Bucket: {GCS_BUCKET_NAME}")
    # Add info about index path or ES connection
    # logging.info(f"Using Whoosh index directory: {INDEX_DIR}")
    # logging.info(f"Connecting to Elasticsearch: {ES_HOST}:{ES_PORT}, Index: {ES_INDEX_NAME}")

    # --- Start Subscriber ---
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_indexing_task)
    logging.info(f"Listening for messages on {subscription_path}...")

    # Keep the main thread alive
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