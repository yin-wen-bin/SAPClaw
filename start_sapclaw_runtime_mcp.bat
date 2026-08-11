@echo off
setlocal

cd /d "%~dp0"

if not defined SAPCLAW_MCP_BASE_URL set "SAPCLAW_MCP_BASE_URL=http://127.0.0.1:8000"
if not defined SAPCLAW_MCP_TIMEOUT set "SAPCLAW_MCP_TIMEOUT=500"

>&2 echo [1/4] Preparing Python environment...
set "PYTHONPATH=%CD%\src"

>&2 echo [2/4] Checking SAPClaw Runtime MCP dependencies...
python -c "import mcp; import sap_odata_agent" 1>NUL 2>NUL
if errorlevel 1 (
  >&2 echo Installing SAPClaw agent dependencies...
  python -m pip install -e ".[agent]" 1>&2
  if errorlevel 1 goto :fail
)

>&2 echo [3/4] Checking SAPClaw Runtime at %SAPCLAW_MCP_BASE_URL% ...
python -c "import os; from sap_odata_agent.agent_tools.runtime_client import SapClawRuntimeClient; result=SapClawRuntimeClient(base_url=os.environ.get('SAPCLAW_MCP_BASE_URL'), timeout_seconds=5).health(); raise SystemExit(0 if result.get('ok') else 1)" 1>NUL 2>NUL
if errorlevel 1 (
  >&2 echo Warning: SAPClaw SAPClaw Runtime is disabled or not reachable.
  >&2 echo Start the API in another terminal with:
  >&2 echo   .\start_agent_ui.bat
)

>&2 echo [4/4] Starting SAPClaw Runtime MCP stdio server...
python -m sap_odata_agent.agent_tools.runtime_mcp_server --base-url "%SAPCLAW_MCP_BASE_URL%" --timeout "%SAPCLAW_MCP_TIMEOUT%" %*
if errorlevel 1 goto :fail
goto :eof

:fail
>&2 echo Startup failed.
exit /b 1
