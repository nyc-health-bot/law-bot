@echo off
setlocal

REM Add gcloud to PATH
set PATH=C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin;%PATH%

REM Copy function source
copy /Y ..\google_function.py main.py

REM Fix Windows line endings in env.yaml (gcloud requires LF)
powershell -Command "$c=[IO.File]::ReadAllText('env.yaml') -replace \"`r`n\",\"`n\"; [IO.File]::WriteAllText('env.yaml',$c)"

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
