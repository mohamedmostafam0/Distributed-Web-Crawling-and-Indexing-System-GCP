import os
import json
import uuid
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, flash, jsonify
from google.cloud import pubsub_v1, storage
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret")

# ENV Variables
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
PUBSUB_TOPIC_ID = os.environ["NEW_CRAWL_JOB_TOPIC_ID"]
METRICS_SUBSCRIPTION_ID = os.environ.get("METRICS_SUBSCRIPTION_ID")
PROGRESS_SUBSCRIPTION_ID = os.environ.get("PROGRESS_SUBSCRIPTION_ID")
ES_HOST = os.environ.get("ES_HOST")
ES_PORT = os.environ.get("ES_PORT")
ES_USERNAME = os.environ.get("ES_USERNAME")
ES_PASSWORD = os.environ.get("ES_PASSWORD")
ES_INDEX_NAME = os.environ.get("ES_INDEX_NAME")

# Clients
storage_client = storage.Client()
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_ID)
subscriber = pubsub_v1.SubscriberClient()
metrics_subscription_path = subscriber.subscription_path(PROJECT_ID, METRICS_SUBSCRIPTION_ID)
progress_subscription_path = subscriber.subscription_path(PROJECT_ID, PROGRESS_SUBSCRIPTION_ID)

# Initialize Elasticsearch client
try:
    es_url = f"https://{ES_USERNAME}:{ES_PASSWORD}@{ES_HOST}"
    es_client = Elasticsearch(es_url, verify_certs=True)
    
    if not es_client.ping():
        print("Warning: Elasticsearch connection failed")
    else:
        print(f"Connected to Elasticsearch at {ES_HOST}:{ES_PORT}")
except Exception as e:
    print(f"Failed to initialize Elasticsearch client: {e}")
    es_client = None

# --- Application State ---
app_state = {
    "tasks": {},   # Task progress information
    "summary": {   # System-wide summary
        "urls_crawled": 0,
        "urls_indexed": 0,
        "active_tasks": 0,
        "completed_tasks": 0,
        "failed_tasks": 0
    },
    "health": {    # Component health status
        "master": {"status": "unknown", "last_check": None},
        "crawler": {"status": "unknown", "last_check": None},
        "indexer": {"status": "unknown", "last_check": None}
    }
}

# Helper function to check if a node is offline based on last health check
def is_node_offline(last_check_time):
    if not last_check_time:
        return True
    
    try:
        # Parse ISO format timestamp
        last_check = datetime.fromisoformat(last_check_time)
        current_time = datetime.utcnow()
        # Check if last health check was more than 2 minutes ago
        time_diff = (current_time - last_check).total_seconds()
        return time_diff > 120  # 2 minutes in seconds
    except Exception as e:
        print(f"Error checking node status: {e}")
        return True  # Assume offline if there's an error

# Helper function to update summary stats
def update_summary_stats():
    active = 0
    completed = 0
    failed = 0
    urls_crawled = 0
    urls_indexed = 0
    
    for task in app_state["tasks"].values():
        if task["status"] == "in_progress":
            active += 1
        elif task["status"] == "completed":
            completed += 1
        elif task["status"] == "failed":
            failed += 1
        
        urls_crawled += task["crawled_urls"]
        urls_indexed += task["indexed_urls"]
    
    app_state["summary"]["active_tasks"] = active
    app_state["summary"]["completed_tasks"] = completed
    app_state["summary"]["failed_tasks"] = failed
    app_state["summary"]["urls_crawled"] = urls_crawled
    app_state["summary"]["urls_indexed"] = urls_indexed


def listen_health_status():
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(PROJECT_ID, "health-metrics-sub")
    
    def callback(msg):
        try:
            data = json.loads(msg.data.decode("utf-8"))
            node_type = data.get("node_type", "unknown")
            status = data.get("status", "unknown")
            timestamp = data.get("timestamp")
            
            if node_type in app_state["health"]:
                app_state["health"][node_type] = {
                    "status": status,
                    "last_check": timestamp,
                    "hostname": data.get("hostname", "unknown")
                }
            
            print(f"Health update: Node {data.get('hostname')} ({node_type}) is {status} at {timestamp}")
        except Exception as e:
            print(f"Error processing health message: {e}")
        finally:
            msg.ack()

    subscriber.subscribe(sub_path, callback=callback)
    

# --- Background Progress Listener ---
def listen_to_progress():
    def callback(message: pubsub_v1.subscriber.message.Message):
        try:
            data = json.loads(message.data.decode("utf-8"))
            task_id = data.get("task_id")
            event = data.get("event")
            timestamp = data.get("timestamp") or datetime.utcnow().isoformat()
            
            if not task_id:
                print(f"Received progress message without task_id: {data}")
                message.ack()
                return
                
            # Initialize task if it doesn't exist
            if task_id not in app_state["tasks"]:
                app_state["tasks"][task_id] = {
                    "task_id": task_id,
                    "status": "in_progress",
                    "crawled_urls": 0,
                    "indexed_urls": 0,
                    "crawled_urls_list": [],  # List of crawled URLs for detail view
                    "indexed_urls_list": [],  # List of indexed URLs for detail view
                    "start_time": timestamp,
                    "last_update": timestamp,
                    "progress_events": [],     # Timeline of progress events
                    "total_depth": data.get("depth", 1),
                    "current_depth": 0,
                    "seed_urls": data.get("seed_urls", []),
                    "domain_restriction": data.get("domain_restriction")
                }
            
            # Update task with the new information
            task = app_state["tasks"][task_id]
            task["last_update"] = timestamp
            
            # Add event to progress timeline
            task["progress_events"].append({
                "event": event,
                "timestamp": timestamp,
                "details": data
            })
            
            # Update based on specific event types
            if event == "task_started":
                task["status"] = "in_progress"
                task["start_time"] = timestamp
                task["total_depth"] = data.get("depth", task["total_depth"])
                task["seed_urls"] = data.get("seed_urls", task["seed_urls"])
                task["domain_restriction"] = data.get("domain_restriction", task["domain_restriction"])
                update_summary_stats()
                
            elif event == "url_crawled":
                task["crawled_urls"] += 1
                url = data.get("url")
                if url and url not in task["crawled_urls_list"]:
                    task["crawled_urls_list"].append(url)
                
                # Update current depth if provided
                depth = data.get("depth")
                if depth is not None and depth > task["current_depth"]:
                    task["current_depth"] = depth
                update_summary_stats()
                
            elif event == "url_indexed":
                task["indexed_urls"] += 1
                url = data.get("url")
                if url and url not in task["indexed_urls_list"]:
                    task["indexed_urls_list"].append(url)
                update_summary_stats()
                
            elif event == "depth_complete":
                depth = data.get("depth")
                if depth is not None:
                    task["depth_complete"] = depth
                update_summary_stats()
                
            elif event == "task_completed":
                task["status"] = "completed"
                task["end_time"] = timestamp
                task["completion_details"] = data
                update_summary_stats()
                
            elif event == "task_failed":
                task["status"] = "failed"
                task["end_time"] = timestamp
                task["error"] = data.get("error", "Unknown error")
                task["error_details"] = data
                update_summary_stats()
            
            # Clean up lists if they're getting too large
            # Keep only the first 10 and the last 40 items to stay under memory limits
            for list_name in ["crawled_urls_list", "indexed_urls_list", "progress_events"]:
                if len(task[list_name]) > 100:
                    task[list_name] = task[list_name][:10] + task[list_name][-40:]
            
            # Update overall summary statistics
            update_summary_stats()
                
        except Exception as e:
            print(f"Error processing progress message: {e}")
        finally:
            message.ack()

    streaming_pull_future = subscriber.subscribe(progress_subscription_path, callback=callback)
    try:
        streaming_pull_future.result()
    except Exception as e:
        print(f"Error in progress listener: {e}")
        streaming_pull_future.cancel()

def periodic_health_check():
    """Periodically check node health even without UI interaction"""
    while True:
        try:
            # Check all nodes for health status
            for component, info in app_state["health"].items():
                if info["last_check"] and is_node_offline(info["last_check"]):
                    app_state["health"][component]["status"] = "offline"
                    print(f"Node {component} marked as offline: no health check in over 2 minutes")
            
            # Sleep for 30 seconds before next check
            time.sleep(30)
        except Exception as e:
            print(f"Error in periodic health check: {e}")
            time.sleep(10)  # Sleep and retry on error

def periodic_updates():
    """Periodically update summary stats and other data that should be refreshed"""
    while True:
        try:
            # Update summary stats to ensure consistency
            update_summary_stats()
            print("Periodically updated summary statistics")
            
            # Sleep for 10 seconds before next update
            time.sleep(10)
        except Exception as e:
            print(f"Error in periodic updates: {e}")
            time.sleep(5)  # Sleep and retry on error

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        seed_urls = [url.strip() for url in request.form.getlist("seed_urls[]") if url.strip()]
        depth = request.form.get("depth_limit", "1")
        domain = request.form.get("domain_restriction", "").strip() or None

        if not seed_urls:
            flash("Please provide at least one valid seed URL.", "error")
            return render_template("index.html", app_state=app_state)

        try:
            depth = int(depth)
        except ValueError:
            flash("Depth must be a valid integer.", "error")
            return render_template("index.html", app_state=app_state) 

        # Generate a task ID
        task_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Create job data
        job_data = {
            "task_id": task_id,
            "seed_urls": seed_urls,
            "depth": depth,
            "domain_restriction": domain,
            "timestamp": timestamp
        }
        
        # Create GCS path
        gcs_blob_path = f"crawl_tasks/{task_id}.json"

        # Upload to GCS
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(gcs_blob_path)
        blob.upload_from_string(json.dumps(job_data), content_type="application/json")

        # Publish to Pub/Sub
        pubsub_msg = {
            "task_id": task_id,
            "gcs_path": f"gs://{GCS_BUCKET_NAME}/{gcs_blob_path}",
            "event": "task_submitted",
            "timestamp": timestamp
        }
        future = publisher.publish(topic_path, json.dumps(pubsub_msg).encode("utf-8"))
        print(f"Published message ID: {future.result()}")
        
        # Initialize task in local state
        app_state["tasks"][task_id] = {
            "task_id": task_id,
            "status": "submitted",
            "crawled_urls": 0,
            "indexed_urls": 0,
            "crawled_urls_list": [],
            "indexed_urls_list": [],
            "start_time": timestamp,
            "last_update": timestamp,
            "progress_events": [{
                "event": "task_submitted",
                "timestamp": timestamp,
                "details": {"seed_urls": seed_urls, "depth": depth, "domain_restriction": domain}
            }],
            "total_depth": depth,
            "current_depth": 0,
            "seed_urls": seed_urls,
            "domain_restriction": domain
        }
        
        # Update summary stats
        update_summary_stats()
        
        flash(f"Crawl job submitted. Task ID: {task_id}", "success")
        return render_template("index.html", app_state=app_state)

    return render_template("index.html", app_state=app_state)

@app.route("/search/urls", methods=["GET"])
def search_urls():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No search query provided"})
    
    try:
        # This would typically fetch data from a database or other storage
        # For now, we'll return mock data
        results = [
            {"url": f"https://example.com/{query}/page1", "last_crawled": "2023-04-15 14:30:22"},
            {"url": f"https://example.org/{query}/page2", "last_crawled": "2023-04-15 15:45:12"}
        ]
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/search/index", methods=["GET"])
def search_index():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No search query provided"})
    
    try:
        if not es_client:
            raise Exception("Elasticsearch client not available")
        
        # Search in Elasticsearch
        search_body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content", "url"]
                }
            },
            "highlight": {
                "fields": {
                    "content": {}
                }
            },
            "size": 10
        }
        
        response = es_client.search(index=ES_INDEX_NAME, body=search_body)
        
        # Process the results
        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            highlight = hit.get("highlight", {})
            snippet = "...".join(highlight.get("content", ["No preview available"]))
            
            results.append({
                "url": source["url"],
                "title": source["url"].split("/")[-1] or source["url"],
                "snippet": snippet
            })
        
        return jsonify({"results": results})
    except Exception as e:
        print(f"Error searching index: {e}")
        return jsonify({"error": str(e)})

@app.route("/progress", methods=["GET"])
def get_progress():
    return jsonify(app_state)

@app.route("/tasks", methods=["GET"])
def get_tasks():
    # Add pagination support
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 10, type=int)
    status_filter = request.args.get("status")
    
    tasks = list(app_state["tasks"].values())
    
    # Apply status filter if provided
    if status_filter:
        tasks = [t for t in tasks if t["status"] == status_filter]
    
    # Sort by last_update, newest first
    tasks.sort(key=lambda x: x.get("last_update", ""), reverse=True)
    
    # Calculate pagination
    total = len(tasks)
    start_idx = (page - 1) * size
    end_idx = min(start_idx + size, total)
    
    # Get the slice for the current page
    current_page_tasks = tasks[start_idx:end_idx]
    
    return jsonify({
        "tasks": current_page_tasks,
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "summary": app_state["summary"]
    })

@app.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    task = app_state["tasks"].get(task_id)
    if task:
        return jsonify({"task": task})
    return jsonify({"error": "Task not found"}), 404

@app.route("/export", methods=["GET"])
def export_index():
    try:
        if not es_client:
            raise Exception("Elasticsearch client not available")
        
        page = request.args.get("page", 1, type=int)
        size = request.args.get("size", 50, type=int)
        
        # Limit size to prevent large responses
        if size > 100:
            size = 100
            
        # Calculate from value for pagination
        from_val = (page - 1) * size
        
        # Query all documents
        query = {
            "query": {
                "match_all": {}
            },
            "from": from_val,
            "size": size,
            "sort": [
                {"url.keyword": {"order": "asc"}}
            ]
        }
        
        response = es_client.search(index=ES_INDEX_NAME, body=query)
        
        # Process results
        total = response["hits"]["total"]["value"]
        results = []
        
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            result = {
                "url": source["url"],
                # Truncate content to prevent large response
                "content_preview": source["content"][:200] + "..." if len(source["content"]) > 200 else source["content"]
            }
            results.append(result)
        
        return jsonify({
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size,  # Calculate total pages
            "results": results
        })
    except Exception as e:
        print(f"Error exporting index: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health_check():
    # Check each component and update status if it's offline
    for component, info in app_state["health"].items():
        if info["last_check"] and is_node_offline(info["last_check"]):
            app_state["health"][component]["status"] = "offline"
    
    return jsonify(app_state["health"])

if __name__ == "__main__":
    threading.Thread(target=listen_health_status, daemon=True).start()
    threading.Thread(target=listen_to_progress, daemon=True).start()
    threading.Thread(target=periodic_health_check, daemon=True).start()
    threading.Thread(target=periodic_updates, daemon=True).start()

    app.run(debug=True, host='0.0.0.0', port=5000)
