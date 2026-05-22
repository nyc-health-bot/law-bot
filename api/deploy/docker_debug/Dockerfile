FROM python:3.11-slim

WORKDIR /workspace

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project
COPY ../../.. /workspace

# Install Python deps (function runtime requirements)
RUN pip install --no-cache-dir -r middle/google_deploy/requirements.txt
RUN pip install --no-cache-dir functions-framework python-dotenv

ENV PORT=8080

# Use the Functions Framework to run the handler in middle/google_deploy/main.py
WORKDIR /workspace/middle/google_deploy
EXPOSE 8080
CMD ["functions-framework", "--target", "handle_request", "--port", "8080"]
