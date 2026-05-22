#!/bin/bash
set -e

BUCKET=$(grep PROMPT_BUCKET env.yaml | awk -F'"' '{print $2}')

gsutil cp ../prompts/structure_question.txt gs://$BUCKET/
gsutil cp ../prompts/structure_response.txt gs://$BUCKET/
gsutil cp ../prompts/structure_summary.txt gs://$BUCKET/
gsutil cp ../prompts/structure_passages.txt gs://$BUCKET/

echo "Prompts deployed to gs://$BUCKET — live within 60 seconds."
