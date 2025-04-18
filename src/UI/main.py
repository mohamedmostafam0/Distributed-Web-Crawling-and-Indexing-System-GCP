import os
import json
import uuid
from flask import Flask, render_template, request, flash
from google.cloud import pubsub_v1, storage
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret")

# ENV Variables
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
PUBSUB_TOPIC_ID = os.environ["NEW_CRAWL_JOB_TOPIC_ID"]

# Clients
storage_client = storage.Client()
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_ID)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        seed_urls = [url.strip() for url in request.form.getlist("seed_urls[]") if url.strip()]
        depth = request.form.get("depth_limit", "1")
        domain = request.form.get("domain_restriction", "").strip() or None

        if not seed_urls:
            flash("Please provide at least one valid seed URL.", "error")
            return render_template("index.html")

        try:
            depth = int(depth)
        except ValueError:
            flash("Depth must be a valid integer.", "error")
            return render_template("index.html")

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
        return render_template("index.html", submitted_data=job_data)

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
