@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

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

"%PYTHON_EXE%" -c "import uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Python dependency check failed for "%PYTHON_EXE%".
  echo Run this once, then start again:
  echo "%PYTHON_EXE%" -m pip install -e .[dev,agent]
  goto :fail
)

echo [4/4] Starting SAP OData Agent UI at http://127.0.0.1:8000 ...
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$url='http://127.0.0.1:8000/'; for ($i=0; $i -lt 30; $i++) { try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/health' | Out-Null; Start-Process $url; exit } catch { Start-Sleep -Seconds 1 } }; Start-Process $url"
"%PYTHON_EXE%" -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
goto :eof

:fail
echo Startup failed.
exit /b 1
