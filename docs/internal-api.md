# SAPClaw Internal Read-Only API

This document describes the read-only API intended for trusted internal tools and agents. It is separate from the browser UI endpoints.

The Codex-first strict execution surface is documented separately in [thin-runtime.md](thin-runtime.md). It runs in parallel with this natural-language API and does not change the request or response contract described below.

## Base URL

Use the deployment URL for your environment:

```text
<SAPCLAW_BASE_URL>
```

For local development this is usually:

```text
http://127.0.0.1:8000
```

## Authentication

`GET /health` is public for local health checks.

`POST /api/v1/queries` and `GET /api/v1/queries/{case_id}/pages` use API-key authentication when `SAPCLAW_API_KEYS` is configured.

External or shared deployments must set:

```powershell
$env:SAPCLAW_API_KEYS = "<replace-with-random-api-key>"
```

Clients then send:

```http
X-API-Key: <SAPCLAW_API_KEY>
```

If `SAPCLAW_API_KEYS` is omitted, the backend allows unauthenticated internal API calls. Use that mode only for local development bound to `127.0.0.1`.

## Query

```http
POST /api/v1/queries
Content-Type: application/json
X-API-Key: <SAPCLAW_API_KEY>
```

Request:

```json
{
  "input": "query supplier <SUPPLIER_ID> basic information",
  "conversation_id": "optional-session-id",
  "llm_profile_id": "optional-profile-id"
}
```

The endpoint forces read-only execution. Caller-supplied `mode` values are rejected.

Success response shape:

```json
{
  "case_id": "case-id",
  "status": "success",
  "message": "Query executed successfully.",
  "answer": "Loaded 1 row.",
  "presentation": {
    "kind": "table",
    "title": "Query results",
    "text": "Loaded 1 row."
  },
  "data": {
    "columns": ["Supplier", "SupplierName"],
    "rows": [
      {
        "Supplier": "<SUPPLIER_ID>",
        "SupplierName": "Example Supplier"
      }
    ],
    "pagination": {
      "page_size": 50,
      "display_limit": 50,
      "skip": 0,
      "page_number": 1,
      "has_next": false,
      "next_skip": null
    }
  },
  "metadata": {
    "service_name": "API_BUSINESS_PARTNER",
    "entity_set": "A_Supplier"
  },
  "duration_ms": 1234.56,
  "error": null
}
```

The response intentionally omits internal plan details, raw SAP metadata, and SAP `__metadata` payloads.

## Clarification

If SAPClaw needs clarification, it returns:

```json
{
  "case_id": "case-id",
  "status": "needs_clarification",
  "message": "Please clarify which company code should be used.",
  "answer": "Please clarify which company code should be used.",
  "presentation": {
    "kind": "text",
    "title": "Query results",
    "text": "Please clarify which company code should be used."
  },
  "data": {
    "columns": [],
    "rows": [],
    "pagination": {}
  },
  "metadata": {
    "service_name": "UNKNOWN",
    "entity_set": "UNKNOWN"
  },
  "duration_ms": 850.2,
  "error": null
}
```

Continue the same conversation by sending the user's clarification with the same `conversation_id` when available.

## Pagination

```http
GET /api/v1/queries/{case_id}/pages?skip=50
X-API-Key: <SAPCLAW_API_KEY>
```

Use `data.pagination.next_skip` from the previous page when present.

## PowerShell Example

```powershell
$headers = @{ "X-API-Key" = "<SAPCLAW_API_KEY>" }
$body = @{
  input = "query supplier <SUPPLIER_ID> basic information"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "<SAPCLAW_BASE_URL>/api/v1/queries" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

## Python Example

```python
import requests

response = requests.post(
    "<SAPCLAW_BASE_URL>/api/v1/queries",
    headers={"X-API-Key": "<SAPCLAW_API_KEY>"},
    json={"input": "query supplier <SUPPLIER_ID> basic information"},
    timeout=60,
)
response.raise_for_status()
print(response.json()["answer"])
```

## JavaScript Example

```javascript
const response = await fetch("<SAPCLAW_BASE_URL>/api/v1/queries", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "<SAPCLAW_API_KEY>"
  },
  body: JSON.stringify({
    input: "query supplier <SUPPLIER_ID> basic information"
  })
});

const payload = await response.json();
console.log(payload.answer);
```

## Public Exposure Boundary

Only expose this read-only internal API behind HTTPS and API-key enforcement. Do not expose local SAP index files, raw metadata, test cases, or the local UI/agent endpoints without equivalent gateway authentication.
