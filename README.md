# SAPClaw

SAPClaw v2 is a guarded, read-only SAP OData Runtime for Codex. Codex performs business interpretation and authors a structured query plan; SAPClaw supplies catalog, schema and business evidence, strictly validates the plan, executes SAP `GET` requests, stores an audit case, and presents pageable results.

SAPClaw does not embed or call an LLM. The v1 LLM-first Router, Planner, Repairer, Verifier, Presenter, Agent API and legacy MCP server were removed in v2.

## Architecture

```text
Codex + sapclaw-odata skill
        |
        v
sapclaw-runtime-mcp (stdio)
        |
        v
/api/v1/runtime/*
        |
        +-- Catalog / API Skill / Knowledge Graph evidence
        +-- indexed and live SAP schema validation
        +-- GET-only OData compiler and executor
        +-- pagination, aggregation, audit case and local viewer
```

The Runtime is the only execution path and is always enabled. If the SAP URL, basic credentials, executable indexes or enabled live-schema support are missing, the service starts in `not_ready` state and reports the missing requirements through `/health`.

## Requirements

- Python 3.11 or newer.
- Node.js 18, 20, or 22+ to build the local viewer.
- An SAP OData endpoint and matching indexes in `data/index/`.
- Codex or another MCP client for planning and user interaction.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev,agent]
Copy-Item .env.example env\.env
npm ci --prefix frontend
npm run build --prefix frontend
```

Edit `env/.env` with the SAP connection, API key, index and viewer settings. No LLM provider credentials are required by SAPClaw v2.

## Start

Start the local FastAPI service and viewer:

```powershell
.\start_agent_ui.bat
```

Or start the API manually:

```powershell
$env:PYTHONPATH="src"
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Check readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Start the MCP server:

```powershell
.\start_sapclaw_runtime_mcp.bat
```

Codex configuration:

```toml
[mcp_servers.sapclaw_runtime]
command = "python"
args = ["-m", "sap_odata_agent.agent_tools.runtime_mcp_server", "--base-url", "http://127.0.0.1:8000", "--timeout", "500"]
cwd = "<SAPCLAW_WORKSPACE>"
env = { PYTHONPATH = "<SAPCLAW_WORKSPACE>\\src" }
env_vars = ["SAPCLAW_API_KEY"]
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 600
```

The Codex workflow skill is located at `skills/sapclaw-odata/`.

## Runtime API and viewer

The protected Runtime API exposes catalog, schema, guidance, plan validation, plan execution, controlled GET, pagination and feedback under `/api/v1/runtime/*`. Configure `SAPCLAW_API_KEYS` to require `X-API-Key` for MCP and execution calls.

Saved cases can be viewed at:

```text
http://127.0.0.1:8000/?case_id=<case-id>&page=1
```

Case viewing and pagination are restricted to loopback clients. The viewer never accepts arbitrary remote URLs.

See `docs/runtime.md` for the complete contracts and safety rules.

## Build indexes and knowledge graph

```powershell
$env:PYTHONPATH="src"
python -m sap_odata_agent.tools.build_dual_source_index --help
python -m sap_odata_agent.tools.build_local_knowledge_graph
```

Index evidence and API skills are advisory for discovery. Indexed and live SAP schemas remain the execution authority.

## Test

```powershell
$env:CI="true"
python -m pytest -q
npm test --prefix frontend
npm run build --prefix frontend
```

The deterministic Runtime E2E runner is available as `sapclaw-runtime-e2e`.

## Security boundary

- Only SAP OData `GET` requests are allowed.
- Payloads, write methods and confirmation-gated write semantics are rejected.
- Query plans and controlled URLs are schema-validated before execution.
- Credentials, local case data and test runs are excluded from source control.
- SAPClaw is an auxiliary query tool; verify critical results in the source SAP system.

## Migrating from v1

v2 is intentionally incompatible with v1. Remove calls to `/api/v1/agent/*`, `/api/v1/queries*` and `sapclaw-mcp`. Remove LLM provider and profile settings, configure `sapclaw-runtime-mcp`, and use the `sapclaw-odata` skill. Users who require the embedded LLM-first flow should remain on the `v1.0.0` release.

SAP, SAP S/4HANA and related product names are trademarks or registered trademarks of SAP SE or its affiliates.
