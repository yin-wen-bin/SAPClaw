---
name: sapclaw-sap-odata
description: Use this skill when an agent needs to answer SAP business questions by calling the local SAPClaw SAP OData natural-language query service. Trigger for SAP OData, SAP master data, supplier, customer, purchase order, sales order, invoice, inventory, material, finance, controlling, production, or cross-API SAP lookup requests.
---

# SAPClaw SAP OData

Use SAPClaw as the authoritative runtime for SAP OData natural-language queries. SAPClaw owns API routing, schema grounding, API-specific playbooks, validation, SAP execution, repair, presentation, and case memory.

## Required Tool

Use the configured `sapclaw` MCP server when available. It exposes:

- `sapclaw_health`
- `sapclaw_query`
- `sapclaw_page`
- `sapclaw_feedback`
- `sapclaw_model_profiles`

The expected local service is `http://127.0.0.1:8000`. This skill does not start SAPClaw automatically.

## Workflow

1. Call `sapclaw_health` before the first query in a session. If it fails, tell the user to start SAPClaw locally and include the returned start command.
2. For SAP business questions, call `sapclaw_query` with the user's natural-language request in `user_input`.
3. Keep `mode` as `read_only` unless the user explicitly requests a write operation and confirms the risk.
4. If SAPClaw returns `needs_clarification=true`, ask the clarification question and pass the user's answer back as a new `sapclaw_query` call with the same `conversation_id` when available.
5. Use `sapclaw_page` only when the user asks for more rows from a previous `case_id`.
6. Use `sapclaw_feedback` when the user marks an answer correct or incorrect.

## Safety

- Do not read, print, summarize, or expose SAP credentials, `env/.env`, connection secrets, raw SAP responses containing sensitive fields, or full local index files.
- Do not copy `data/index` or `data/api_skills` into prompts. SAPClaw loads those internally.
- Do not bypass SAPClaw by constructing raw SAP OData requests unless the user explicitly asks for low-level debugging.
- Prefer concise business answers based on SAPClaw's `final_message`, `presentation`, and `data`.

## References

- Read `references/http-api.md` if the MCP server is unavailable and direct HTTP fallback is needed.
- Read `references/examples.md` for parameter examples and common interaction patterns.
