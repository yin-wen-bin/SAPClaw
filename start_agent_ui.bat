@echo off
setlocal

cd /d "%~dp0"

echo [1/4] Checking frontend dependencies...
if not exist "frontend\node_modules" (
  echo Installing frontend dependencies...
  call npm install --prefix frontend
  if errorlevel 1 goto :fail
)

echo [2/4] Building React frontend...
call npm run build --prefix frontend
if errorlevel 1 goto :fail

echo [3/4] Preparing Python environment...
set "PYTHONPATH=%CD%\src"

echo [4/4] Starting SAP OData Agent UI at http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
goto :eof

:fail
echo Startup failed.
exit /b 1
