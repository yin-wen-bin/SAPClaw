# SAPClaw HTTP API

Default local base URL:

```text
http://127.0.0.1:8000
```

SAPClaw must already be running:

```powershell
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

## Health

`GET /health`

Success:

```json
{"status": "ok"}
```

## Query

`POST /api/v1/agent/query`

Request:

```json
{
  "user_input": "query supplier <SUPPLIER_ID> basic information",
  "conversation_id": "optional-session-id",
  "mode": "read_only",
  "llm_profile_id": "optional-profile-id"
}
```

Response fields used by agents:

- `success`
- `case_id`
- `final_message`
- `needs_clarification`
- `clarification_question`
- `clarification_options`
- `presentation`
- `data`
- `plan`
- `attempts`

## Page

`POST /api/v1/agent/page`

```json
{"case_id": "case id returned by query", "skip": 50}
```

Use when the user asks for the next page or more rows from a previous result.

## Feedback

`POST /api/v1/agent/feedback`

```json
{
  "case_id": "case id returned by query",
  "status": "incorrect",
  "comment": "The answer used the wrong business status field.",
  "expected_result": "Use the completion status field."
}
```

`status` must be `correct` or `incorrect`.

## Model Profiles

`GET /api/v1/agent/model-profiles`

Use only when the user asks which LLM profiles SAPClaw can use, or when choosing a configured `llm_profile_id`.
