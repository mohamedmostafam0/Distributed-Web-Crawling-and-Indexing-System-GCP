import os
import json
import uuid
import threading
from flask import Flask, render_template, request, flash, jsonify
from google.cloud import pubsub_v1, storage
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret")

# ENV Variables
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
PUBSUB_TOPIC_ID = os.environ["NEW_CRAWL_JOB_TOPIC_ID"]
METRICS_SUBSCRIPTION_ID = os.environ.get("METRICS_SUBSCRIPTION_ID")

# Clients
storage_client = storage.Client(project=PROJECT_ID)
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_ID)
subscriber = pubsub_v1.SubscriberClient()
metrics_subscription_path = subscriber.subscription_path(PROJECT_ID, METRICS_SUBSCRIPTION_ID)

# --- Metrics State ---
metrics_state = {
    "urls_crawled": 0,
    "urls_indexed": 0
}

# --- Background Metrics Listener ---
def listen_to_metrics():
    def callback(message: pubsub_v1.subscriber.message.Message):
        try:
            data = json.loads(message.data.decode("utf-8"))
            event = data.get("event")
            if event == "url_crawled":
                metrics_state["urls_crawled"] += 1
            elif event == "url_indexed":
                metrics_state["urls_indexed"] += 1
        except Exception as e:
            print(f"Error processing metrics message: {e}")
        finally:
            message.ack()

    streaming_pull_future = subscriber.subscribe(metrics_subscription_path, callback=callback)
    try:
        streaming_pull_future.result()
    except Exception as e:
        streaming_pull_future.cancel()

# Start background thread
threading.Thread(target=listen_to_metrics, daemon=True).start()

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        seed_urls = [url.strip() for url in request.form.getlist("seed_urls[]") if url.strip()]
        depth = request.form.get("depth_limit", "1")
        domain = request.form.get("domain_restriction", "").strip() or None

        if not seed_urls:
            flash("Please provide at least one valid seed URL.", "error")
            return render_template("index.html", metrics=metrics_state)

        try:
            depth = int(depth)
        except ValueError:
            flash("Depth must be a valid integer.", "error")
            return render_template("index.html", metrics=metrics_state) 

        task_id = str(uuid.uuid4())
        gcs_blob_path = f"crawl_tasks/{task_id}.json"

        job_data = {
            "task_id": task_id,
            "seed_urls": seed_urls,
            "depth": depth,
            "domain_restriction": domain
        }

        # Upload to GCS
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_string(json.dumps(job_data), content_type="application/json")

        # Publish to Pub/Sub
        pubsub_msg = {
            "task_id": task_id,
            "gcs_path": f"gs://{GCS_BUCKET_NAME}/{gcs_blob_path}"
        }
        future = publisher.publish(topic_path, json.dumps(pubsub_msg).encode("utf-8"))
        print(f"Published message ID: {future.result()}")
        
        flash(f"Crawl job submitted. Task ID: {task_id}", "success")
        return render_template("index.html", metrics=metrics_state)

    return render_template("index.html", metrics=metrics_state)

@app.route("/search/urls", methods=["GET"])
def search_urls():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    # TODO: Implement URL search logic
    # For now, return mock data
    return jsonify({
        "results": [
            {"url": "https://example.com", "last_crawled": "2024-05-02"},
            {"url": "https://example.org", "last_crawled": "2024-05-01"}
        ]
    })

@app.route("/search/index", methods=["GET"])
def search_index():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No search query provided"}), 400
    
    # TODO: Implement index search logic
    # For now, return mock data
    return jsonify({
        "results": [
            {"url": "https://example.com", "title": "Example Page", "snippet": "This is an example page..."},
            {"url": "https://example.org", "title": "Another Page", "snippet": "This is another example..."}
        ]
    })

@app.route("/health", methods=["GET"])
def health_check():
    # TODO: Implement actual health checks
    return jsonify({
        "crawler": {"status": "running", "last_check": "2024-05-02T12:00:00Z"},
        "indexer": {"status": "running", "last_check": "2024-05-02T12:00:00Z"},
        "storage": {"status": "connected", "last_check": "2024-05-02T12:00:00Z"}
    })

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5001)
