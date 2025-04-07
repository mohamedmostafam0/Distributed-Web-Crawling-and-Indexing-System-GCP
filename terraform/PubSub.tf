resource "google_pubsub_topic" "my_topic" {
  project = var.project_id
  name    = var.pubsub_topic_name
}

resource "google_pubsub_subscription" "my_subscription" {
  project = var.project_id
  name    = var.pubsub_subscription_name
  topic   = google_pubsub_topic.my_topic.name
  ack_deadline_seconds = 10
}
