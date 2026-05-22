@echo off
setlocal

REM Add gcloud to PATH
set PATH=C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin;%PATH%

REM Generate env.yaml from repo-root .env (do not edit env.yaml directly)
python "%~dp0gen_env_yaml.py"

REM Copy function source
copy /Y ..\cloud_function.py main.py

REM Deploy
gcloud functions deploy law-bot ^
  --gen2 ^
  --runtime python312 ^
  --trigger-http ^
  --allow-unauthenticated ^
  --entry-point handle_request ^
  --region us-east1 ^
  --project nyc-health-law-bot ^
  --source . ^
  --env-vars-file env.yaml ^
  --min-instances 1 ^
  --quiet

pause
