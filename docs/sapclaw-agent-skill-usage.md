# SAPClaw Agent Skill Usage

SAPClaw can be exposed to another agent through the `skills/sapclaw-sap-odata` skill and the `sapclaw-mcp` server.

The integration flow is:

```text
External agent
  -> sapclaw-sap-odata skill
  -> sapclaw-mcp tools
  -> local SAPClaw FastAPI service
  -> SAP OData plus local API indexes
```

## Install

From the SAPClaw workspace:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[agent]
```

## Start SAPClaw

```powershell
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

For local UI usage, the repository also provides:

```powershell
.\start_agent_ui.bat
```

## Configure The MCP Server

Use the installed console command:

```json
{
  "name": "sapclaw",
  "command": "sapclaw-mcp",
  "args": ["--base-url", "http://127.0.0.1:8000"]
}
```

If your agent runtime requires an absolute executable path, use a local placeholder in documentation or private configuration:

```json
{
  "command": "<SAPCLAW_WORKSPACE>/.venv/Scripts/sapclaw-mcp.exe",
  "args": ["--base-url", "<SAPCLAW_BASE_URL>"]
}
```

Do not publish machine-specific paths.

## Skill Location

The skill lives at:

```text
skills/sapclaw-sap-odata
```

If your agent supports workspace skills, point it to the workspace `skills/` directory.

## Available MCP Tools

- `sapclaw_health`: checks whether the SAPClaw service is reachable.
- `sapclaw_query`: sends a natural-language SAP query.
- `sapclaw_page`: loads another page for a prior query result.
- `sapclaw_feedback`: records whether a result is correct or incorrect.
- `sapclaw_model_profiles`: lists configured LLM profiles.

## Recommended Agent Flow

1. Call `sapclaw_health` before the first query.
2. Call `sapclaw_query` with the user's original wording.
3. Keep `mode` as `read_only` unless the user explicitly requests a write action and confirms the risk.
4. If `needs_clarification` is true, ask the clarification question and continue with the same `conversation_id` when available.
5. Use `sapclaw_page` when the user asks for more rows.
6. Use `sapclaw_feedback` when the user marks a result correct or incorrect.

## Security Rules

- Do not read or expose `env/.env`.
- Do not copy `env/.env`, raw OpenAPI JSON, raw SAP metadata, or test case assets into prompts.
- The committed `data/index/` files are runtime grounding assets; external agents should receive compact catalog/schema context through SAPClaw, not raw index dumps.
- Do not expose raw SAP OData URLs to end users unless they ask for debugging detail.
- Keep SAPClaw on `127.0.0.1` for local development.
- For any shared deployment, require `SAPCLAW_API_KEYS` and place SAPClaw behind HTTPS plus gateway authentication.
