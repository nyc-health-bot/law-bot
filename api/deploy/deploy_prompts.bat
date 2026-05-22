@echo off
setlocal

REM Add gcloud to PATH
set PATH=C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin;%PATH%

set BUCKET=law-bot-prompts

gsutil cp ..\prompts\structure_question.txt gs://%BUCKET%/
gsutil cp ..\prompts\structure_response.txt gs://%BUCKET%/
gsutil cp ..\prompts\structure_summary.txt gs://%BUCKET%/
gsutil cp ..\prompts\structure_passages.txt gs://%BUCKET%/

echo Prompts deployed to gs://%BUCKET%/ -- live within 60 seconds.
pause
