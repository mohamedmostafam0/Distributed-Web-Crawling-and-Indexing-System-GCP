# Dockerfile
FROM python:3.10-slim

# Create app directory
WORKDIR /app

# Copy files
COPY indexer_node.py .
COPY .env .
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Entrypoint
CMD ["python", "indexer_node.py"]
