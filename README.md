# Distributed-Web-Crawling-and-Indexing-System-GCP

# Web Crawling and Indexing System

This distributed system crawls web pages, processes their content, and indexes them using Elasticsearch running on Google Cloud Platform.

## Features

- **New Crawl**: Submit new crawling tasks with configurable depth and domain restrictions
- **Search URLs**: Search through crawled URLs
- **Search Index**: Full-text search capabilities for indexed content
- **Export Index Data**: View and export the indexed data from Elasticsearch
- **Monitor Progress**: Track the progress of crawling and indexing tasks in real-time
- **System Health**: Monitor the health of system components

## System Architecture

The system consists of the following components:

1. **UI**: Flask web application for user interaction
2. **Master**: Coordinates crawling tasks
3. **Crawler**: Distributed crawlers that process web pages
4. **Indexer**: Indexes processed content in Elasticsearch
5. **GCP Services**:
   - **Pub/Sub**: For message passing between components
   - **Cloud Storage**: For storing crawl tasks and processed content
   - **Elasticsearch**: Managed service for indexing and searching content

## Setup Instructions

### Prerequisites

- Google Cloud Platform account
- Elasticsearch managed service on GCP
- Python 3.8+
- Docker (for containerized deployment)

### Environment Variables

Create a `.env` file with the following variables:

```
GCP_PROJECT_ID=your-project-id
GCS_BUCKET_NAME=your-storage-bucket
NEW_CRAWL_JOB_TOPIC_ID=new-crawl-jobs
METRICS_SUBSCRIPTION_ID=metrics-subscription
PROGRESS_SUBSCRIPTION_ID=progress-subscription
ES_HOST=your-elasticsearch-host
ES_PORT=9243
ES_USERNAME=your-es-username
ES_PASSWORD=your-es-password
ES_INDEX_NAME=web_content
FLASK_SECRET_KEY=your-secret-key
```

### Running the UI

1. Navigate to the UI directory:

   ```
   cd src/UI
   ```

2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Run the Flask application:

   ```
   python main.py
   ```

4. Access the UI at `http://localhost:5000`

## Using the System

### Starting a New Crawl

1. Go to the "New Crawl" tab
2. Enter seed URLs (one per line)
3. Set the crawl depth
4. Optionally set domain restrictions
5. Click "Start Crawling"

### Searching Indexed Content

1. Go to the "Search Index" tab
2. Enter keywords to search
3. Click "Search"

### Exporting Indexed Data

1. Go to the "Search Index" tab
2. Click "Export Index Data"
3. Browse through paginated results

### Monitoring Progress

1. Go to the "Monitor Progress" tab
2. View real-time metrics on crawled and indexed URLs
3. Track individual task progress

## Deployment

For production deployment, use the provided Dockerfiles to build containers for each component:

```
# Build UI container
docker build -t web-crawler-ui ./src/UI

# Build Indexer container
docker build -t web-crawler-indexer ./src/indexer

# Deploy to your container orchestration platform
```

## Customization

- Edit the Elasticsearch index mapping in `indexer_node.py` to modify how content is indexed
- Modify the UI templates in `src/UI/templates` to change the user interface
