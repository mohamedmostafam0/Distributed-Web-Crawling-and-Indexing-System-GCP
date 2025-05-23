# terraform-crawler-infra/monitoring.tf

# --- Notification Channel (Example: Email) ---
# You typically define this once and reuse it.
# Or create/manage channels via GCP Console / gcloud CLI.
resource "google_monitoring_notification_channel" "email" {
  # count        = var.create_notification_channel ? 1 : 0 # Optional toggle
  display_name = "Email Admins"
  type         = "email"
  project      = var.gcp_project_id
  labels = {
    email_address = "mohamed1401@icloud.com"
  }
  description = "Send alerts via email"
  enabled     = true
}


# --- Alert Policy for High CPU on Master Node ---
resource "google_monitoring_alert_policy" "master_cpu_high" {
  display_name = "${var.project_prefix}-master-cpu-high"
  project      = var.gcp_project_id
  combiner     = "OR" # Condition combiner: OR / AND
    http_check {
    port         = "8080"
    path         = "/health"
    use_ssl      = true
    validate_ssl = true
  }
  conditions {
    display_name = "Master CPU Utilization >= 80% for 10m"
    condition_threshold {
      filter     = "metric.type=\"compute.googleapis.com/instance/cpu/utilization\" resource.type=\"gce_instance\" resource.label.\"instance_id\"=\"${google_compute_instance.master.instance_id}\""
      duration   = "600s" # 10 minutes duration
      comparison = "COMPARISON_GT" # Greater than
      threshold_value = 0.8 # 80% utilization (value is between 0.0 and 1.0)
      aggregations {
        alignment_period   = "60s" # Check every minute
        per_series_aligner = "ALIGN_MEAN" # Average over the alignment period
      }
      trigger {
        # Trigger if the condition is met for the full duration
        percent = 100
      }
    }
  }

  alert_strategy {
     # Configure how notifications behave
     # auto_close = "900s" # Example: Auto-close after 15 mins
  }

  # Link the notification channel created above
  notification_channels = [
      google_monitoring_notification_channel.email.id
  ]

  documentation {
    content = "The CPU utilization on the master node (${google_compute_instance.master.name}) has exceeded 80%."
    mime_type = "text/markdown"
  }

  user_labels = merge(var.common_labels, {
     severity = "warning",
     role     = "master"
  })

  depends_on = [google_compute_instance.master]
}

resource "google_monitoring_uptime_check_config" "crawler_health" {
  count        = var.crawler_count
  display_name = "${var.project_prefix}-crawler-${count.index + 1}-health-check"
  timeout      = "10s"
  period       = "60s"

  http_check {
    port         = "8080"
    path         = "/health"
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      host = google_compute_instance.crawler[count.index].network_interface[0].access_config[0].nat_ip
    }
  }
  notification_channels = [
    google_monitoring_notification_channel.email.id
  ]

    documentation {
    content = "The CPU utilization on the crawler node (${google_compute_instance.crawler.name}) has exceeded 80%."
    mime_type = "text/markdown"
  }

  user_labels = merge(var.common_labels, {
     severity = "warning",
     role     = "crawler"
  })

  depends_on = [google_compute_instance.crawler]

}


resource "google_monitoring_uptime_check_config" "indexer_health" {
  count        = var.indexer_count
  display_name = "${var.project_prefix}-indexer-${count.index + 1}-health-check"
  timeout      = "10s"
  period       = "60s"

  http_check {
    port         = "8080"
    path         = "/health"
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      host = google_compute_instance.indexer[count.index].network_interface[0].access_config[0].nat_ip
    }
  }
  notification_channels = [
    google_monitoring_notification_channel.email.id
  ]

    documentation {
    content = "The CPU utilization on the indexer node (${google_compute_instance.indexer.name}) has exceeded 80%."
    mime_type = "text/markdown"
  }

  user_labels = merge(var.common_labels, {
     severity = "warning",
     role     = "indexer"
  })

  depends_on = [google_compute_instance.indexer]
}


# --- TODO: Add similar Alert Policies for Crawlers and Indexers ---
# You would iterate using count or for_each based on the instance resources.
# The filter would need to target the specific instance IDs or use group filters if using MIGs.
# Example structure (needs adaptation for loop):
# resource "google_monitoring_alert_policy" "crawler_cpu_high" {
#   count        = var.crawler_count
#   display_name = "${var.project_prefix}-crawler-${count.index+1}-cpu-high"
#   project      = var.gcp_project_id
#   combiner     = "OR"
#   conditions { ... filter = "... resource.label.\"instance_id\"=\"${google_compute_instance.crawler[count.index].instance_id}\" ..."}
#   ... other settings ...
#   notification_channels = [google_monitoring_notification_channel.email.id]
#   user_labels = { severity = "warning", role = "crawler" }
# }







# ==========================================
# 3. Stackdriver Monitoring + Alert Policies
# ==========================================


