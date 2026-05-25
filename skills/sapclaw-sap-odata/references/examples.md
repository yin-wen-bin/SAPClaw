# SAPClaw Agent Examples

## Basic Query

User:

```text
query supplier <SUPPLIER_ID> basic information
```

Tool call:

```json
{
  "user_input": "query supplier <SUPPLIER_ID> basic information",
  "mode": "read_only"
}
```

Answer from `final_message` first. Use `presentation.rows` for table-style results.

## Clarification

If `sapclaw_query` returns:

```json
{
  "needs_clarification": true,
  "clarification_question": "Which company code should be used?",
  "clarification_options": ["<COMPANY_CODE>", "<OTHER_COMPANY_CODE>"]
}
```

Ask the user the clarification question. When the user answers, call:

```json
{
  "user_input": "<COMPANY_CODE>",
  "conversation_id": "same conversation id if available",
  "mode": "read_only"
}
```

## Paging

If the user asks for more rows after a result with `case_id=abc`, call:

```json
{"case_id": "abc", "skip": 50}
```

Choose `skip` from the previous page size when known. Use `50` as the default page offset.

## Feedback

If the user says the answer is wrong:

```json
{
  "case_id": "abc",
  "status": "incorrect",
  "comment": "The result used the wrong status field.",
  "expected_result": "Use the completion status field."
}
```
