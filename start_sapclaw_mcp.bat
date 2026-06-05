@echo off
setlocal

cd /d "%~dp0"

if not defined SAPCLAW_MCP_BASE_URL set "SAPCLAW_MCP_BASE_URL=http://127.0.0.1:8000"
if not defined SAPCLAW_MCP_TIMEOUT set "SAPCLAW_MCP_TIMEOUT=500"

>&2 echo [1/4] Preparing Python environment...
set "PYTHONPATH=%CD%\src"

>&2 echo [2/4] Checking SAPClaw MCP dependencies...
python -c "import mcp; import sap_odata_agent" 1>NUL 2>NUL
if errorlevel 1 (
  >&2 echo Installing SAPClaw agent dependencies...
  python -m pip install -e ".[agent]" 1>&2
  if errorlevel 1 goto :fail
)

>&2 echo [3/4] Checking SAPClaw API service at %SAPCLAW_MCP_BASE_URL% ...
python -c "import os; from sap_odata_agent.agent_tools.client import SapClawClient; SapClawClient(base_url=os.environ.get('SAPCLAW_MCP_BASE_URL'), timeout_seconds=5).health()" 1>NUL 2>NUL
if errorlevel 1 (
  >&2 echo Warning: SAPClaw API service is not reachable.
  >&2 echo Start the API in another terminal with:
  >&2 echo   .\start_agent_ui.bat
  >&2 echo The MCP server will start, but its tools will fail until the API is available.
)

>&2 echo [4/4] Starting SAPClaw MCP stdio server...
python -m sap_odata_agent.agent_tools.mcp_server --base-url "%SAPCLAW_MCP_BASE_URL%" --timeout "%SAPCLAW_MCP_TIMEOUT%" %*
if errorlevel 1 goto :fail
goto :eof

:fail
>&2 echo Startup failed.
exit /b 1
