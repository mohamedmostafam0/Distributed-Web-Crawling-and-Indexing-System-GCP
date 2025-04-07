# Topic for Master -> Crawlers
resource "google_pubsub_topic" "crawl_tasks" {
  project = var.gcp_project_id
  name    = var.crawl_tasks_topic_name
  labels  = var.common_labels
}

# Subscription for Crawlers to receive tasks
resource "google_pubsub_subscription" "crawl_tasks_sub" {
  project = var.gcp_project_id
  name    = var.crawl_tasks_subscription_name
  topic   = google_pubsub_topic.crawl_tasks.name
  labels  = var.common_labels

  # Increase if tasks take longer, decrease for faster retry on failure
  ack_deadline_seconds = 60
  # Consider configuring retry_policy and dead_letter_policy for production
}

# Topic for Crawlers -> Indexers
resource "google_pubsub_topic" "index_queue" {
  project = var.gcp_project_id
  name    = var.index_queue_topic_name
  labels  = var.common_labels
}

# Subscription for Indexers to receive tasks
resource "google_pubsub_subscription" "index_queue_sub" {
  project = var.gcp_project_id
  name    = var.index_queue_subscription_name
  topic   = google_pubsub_topic.index_queue.name
  labels  = var.common_labels

  ack_deadline_seconds = 120 # Indexing might take longer
  # Consider configuring retry_policy and dead_letter_policy for production
}