# =========================================
# 1. ElasticSearch on GKE using Helm Chart
# =========================================


terraform {
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }
}

provider "helm" {
  kubernetes {
    config_path = "~/.kube/config"
  }
}


resource "helm_release" "elasticsearch" {
  name       = "elasticsearch"
  namespace  = "default"
  repository = "https://helm.elastic.co"
  chart      = "elasticsearch"
  version    = "7.17.3"

  set {
    name  = "replicas"
    value = 2
  }

  set {
    name  = "resources.requests.memory"
    value = "512Mi"
  }

  set {
    name  = "resources.requests.cpu"
    value = "500m"
  }

  set {
    name  = "esJavaOpts"
    value = "-Xmx512m -Xms512m"
  }

  set {
    name  = "persistence.enabled"
    value = "true"
  }

  depends_on = [google_container_cluster.webcrawler_cluster]
}