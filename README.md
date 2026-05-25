# SAPClaw

SAPClaw is a local-first SAP OData natural-language query agent. It uses an LLM to route a user's business question to SAP APIs, build an executable OData plan, validate the plan against indexed SAP metadata, execute read-only SAP requests, and present the result in a business-friendly format.

The project is designed for private SAP landscapes. Public repository artifacts intentionally exclude local SAP metadata, raw API specifications, evaluation cases, credentials, generated frontend bundles, dependency folders, and runtime caches.

## Architecture

- FastAPI backend for query orchestration and UI APIs.
- React frontend under `frontend/`.
- LLM-first SAP OData pipeline: API router, schema context provider, API-specific planner, plan repair, schema validator, SAP executor, result verifier, and presenter.
- API skill files under `data/api_skills/` for API-specific business knowledge.
- Local index files under `data/index/` at runtime. These files are not published and must be generated or copied locally.

## Repository Contents

Published:

- `src/`: backend application and agent tooling.
- `frontend/`: frontend source.
- `data/api_skills/`: API-specific planning guidance.
- `docs/`: public operational documentation.
- `skills/`: optional SAPClaw agent skill integration.
- `tests/`: unit and integration tests that do not contain SAP credentials.

Not published:

- `env/`, `.env`, `.env.*`
- `data/index/`
- `data/metadata/`
- `data/api_test_cases/`
- `data/cross_api_test_cases/`
- `raw/`
- `frontend/dist/`
- `frontend/node_modules/`

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev,agent]
```

Create local configuration:

```powershell
Copy-Item .env.example env\.env
```

Then edit `env/.env` with your SAP and LLM credentials. Do not commit `env/.env`.

## Runtime Data

SAPClaw needs local API index files to route and validate SAP OData requests. By default the backend reads them from:

```text
data/index/
```

Build or copy the index files locally before running real SAP queries. Raw SAP OpenAPI and metadata artifacts should remain local and are intentionally ignored by Git.

## Run The Backend

```powershell
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## Run The Frontend

```powershell
npm install --prefix frontend
npm run dev --prefix frontend
```

For a production build:

```powershell
npm run build --prefix frontend
```

## External Access And Authentication

SAPClaw should be bound to `127.0.0.1` for local development.

For any external, shared, or reverse-proxy deployment:

- Set `SAPCLAW_API_KEYS` to one or more high-entropy API keys.
- Require callers of the public query endpoint to send `X-API-Key`.
- Put SAPClaw behind HTTPS and an authenticated reverse proxy.
- Do not expose `env/`, local index files, raw SAP metadata, or test case assets.
- Treat `/api/v1/agent/*` as a local UI/agent integration surface unless you add equivalent gateway authentication in front of it.

See `SECURITY.md` for the release security policy.

## Disclaimer

SAPClaw is a personal testing and experimental tool for exploring natural-language access to SAP OData APIs.

This project is provided for learning, prototyping, and internal evaluation purposes only. It is not intended for production use, financial reporting, compliance decisions, or any business-critical operation.

The tool may generate incorrect API routes, query plans, filters, field selections, summaries, or business interpretations. Users are responsible for verifying all results directly against the source SAP system before relying on them.

This project does not include any warranty of accuracy, completeness, availability, security, or fitness for a particular purpose. Use it at your own risk.

Do not commit or publish real credentials, API keys, SAP connection details, customer data, supplier data, financial data, or other confidential business information.

SAP, SAP S/4HANA, and related product names are trademarks or registered trademarks of SAP SE or its affiliates.

## Tests

```powershell
python -m pytest -q
npm run build --prefix frontend
```

Some tests exercise local API index behavior and require `data/index/` to exist in the developer environment.
