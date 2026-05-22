#!/bin/bash
set -e

# Copy function source (main.py is generated — do not edit it directly; edit ../cloud_function.py)
cp ../cloud_function.py main.py

gcloud functions deploy law-bot \
  --gen2 \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point handle_request \
  --region us-east1 \
  --project nyc-health-law-bot \
  --source . \
  --env-vars-file env.yaml \
  --timeout=300s
  --min-instances 1 \
  --quiet
