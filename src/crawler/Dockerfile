# Dockerfile
FROM python:3.10-slim

# Create app directory
WORKDIR /app

# Copy files
COPY crawler_node.py .
COPY .env .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Entrypoint
CMD ["python", "crawler_node.py"]
