# src/UI/main.py (Modifications)
import os
import json
from flask import Flask, render_template, request, flash # Added flash
from google.cloud import pubsub_v1
from google.api_core import exceptions
from dotenv import load_dotenv

load_dotenv() # Load .env from src/UI/ or project root if needed

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default-secret-key") # Needed for flash messages

# --- Configuration ---
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
NEW_CRAWL_JOB_TOPIC_ID = os.environ.get("NEW_CRAWL_JOB_TOPIC_ID") # Add this to your .env

# --- Initialize Pub/Sub Publisher ---
publisher = None
new_job_topic_path = None
if PROJECT_ID and NEW_CRAWL_JOB_TOPIC_ID:
    try:
        publisher = pubsub_v1.PublisherClient()
        new_job_topic_path = publisher.topic_path(PROJECT_ID, NEW_CRAWL_JOB_TOPIC_ID)
        print(f"UI Publisher initialized for topic: {new_job_topic_path}")
    except Exception as e:
        print(f"Error initializing UI Pub/Sub Publisher: {e}")
        publisher = None # Ensure publisher is None if init fails
else:
    print("Warning: GCP_PROJECT_ID or NEW_CRAWL_JOB_TOPIC_ID not set. UI cannot submit jobs.")


@app.route("/", methods=["GET", "POST"])
def home():
    submitted_data = None
    if request.method == "POST":
        seed_urls_raw = request.form.get("seed_urls")
        depth_limit_raw = request.form.get("depth_limit")
        domain_restriction = request.form.get("domain_restriction") # Can be empty

        seed_urls = [url.strip() for url in seed_urls_raw.splitlines() if url.strip()]

        # Basic validation
        if not seed_urls:
            flash("Please provide at least one seed URL.", "error")
            return render_template("index.html", submitted_data=None)

        try:
             depth_limit = int(depth_limit_raw) if depth_limit_raw else 0 # Default depth if empty
        except ValueError:
             flash("Depth limit must be a number.", "error")
             return render_template("index.html", submitted_data=None)


        job_data = {
            "seed_urls": seed_urls,
            "depth_limit": depth_limit,
            "domain_restriction": domain_restriction or None, # Send null if empty
        }

        # --- Publish Job to Pub/Sub ---
        if publisher and new_job_topic_path:
            try:
                data = json.dumps(job_data).encode("utf-8")
                future = publisher.publish(new_job_topic_path, data)
                message_id = future.result(timeout=30) # Wait for confirmation
                print(f"Published new crawl job message ID: {message_id}")
                flash(f"Crawl job submitted successfully! (Job ID reference: {message_id})", "success")
                submitted_data = job_data # Keep data to display if needed
            except exceptions.NotFound:
                print(f"Error: Pub/Sub topic not found: {new_job_topic_path}")
                flash("Error submitting job: Topic not found.", "error")
            except TimeoutError:
                print(f"Error: Timeout publishing job to {new_job_topic_path}")
                flash("Error submitting job: Request timed out.", "error")
            except Exception as e:
                print(f"Error publishing job: {e}", exc_info=True)
                flash(f"Error submitting job: {e}", "error")
        else:
             print("Error: UI Publisher not initialized. Cannot submit job.")
             flash("Error submitting job: System not configured.", "error")

        # Display submitted data even if publish fails, allows user to see what they entered
        return render_template("index.html", submitted_data=submitted_data)

    return render_template("index.html", submitted_data=None)

if __name__ == "__main__":
    # Set host='0.0.0.0' to allow external connections if running in a container/VM
    app.run(debug=True, host='0.0.0.0', port=5000)