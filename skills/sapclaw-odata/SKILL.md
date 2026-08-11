---
name: sapclaw-odata
description: Use SAPClaw's read-only Runtime MCP to answer natural-language SAP questions when Codex must choose indexed APIs, inspect authoritative OData schema, build and repair a structured QueryPlan, execute guarded SAP GET requests, page prior results, or record result feedback.
---

# SAPClaw OData

Use Codex for business interpretation and planning. Use SAPClaw only for evidence, schema authority, validation, read-only execution, pagination, and audit.

## Required Workflow

1. Call `sapclaw_runtime_health`. Stop if it returns `not_ready`; report the index, SAP credential, connectivity, or live-schema diagnostic it provides.
2. Call `sapclaw_catalog` with the user's original question. Page the catalog only as needed to identify plausible executable services. Treat both `kg_api_evidence` and `skill_api_evidence` as candidate lists, and do not ignore a service surfaced by either list without checking its schema and guidance.
3. Call `sapclaw_schema` for candidate services. Inspect exact entities, fields, types, relations, and function imports.
4. Call `sapclaw_guidance` for the original question and candidate services. Treat Skill, KG, and feedback items as advisory evidence only.
5. Build a strict QueryPlan with an `output_contract`. Use only fields, entities, paths, functions, and services proven by `sapclaw_schema`. Leave `top` as `null` unless the user explicitly asks for a limit.
6. Call `sapclaw_validate_plan`. If validation fails, repair only from returned issues and authoritative schema. Make at most three validate-repair attempts.
7. Call `sapclaw_execute_plan` after validation succeeds. Use `sapclaw_execute_get` only for a controlled relative GET that is clearer than a structured plan.
8. If SAP execution fails, repair from the structured SAP error and schema, then revalidate. Make at most three total execution-repair rounds.
9. After a successful execution response with a `case_id`, call `sapclaw_runtime_open_viewer` with that case ID before answering. The tool opens the saved local result page in the system default browser only for multi-row, pageable, or detailed results. It keeps an empty or compact single-result answer in Codex. If opening fails, continue with the answer and report that the local viewer could not be opened.
10. Answer in the user's language. State the total count, current row range, and relevant selected fields. Keep `viewer_url` as optional runtime metadata only. Do not render it as a Markdown or clickable link in Codex Desktop; continue pagination through `sapclaw_runtime_page`.

Never invent schema, bypass validation, or treat KG/Skill/feedback evidence as execution authority.

## Output Contract

Every new structured plan must include an `output_contract` with schema field names:

```json
{
  "mode": "explicit | inferred",
  "display_grain": "business grain of each displayed row",
  "requested_fields": ["SchemaField"],
  "display_fields": ["SchemaField"],
  "support_fields": ["SchemaField"],
  "reason": "Why these fields answer the user's question"
}
```

- If the user explicitly names return fields, use `mode: "explicit"`. Resolve each requested business field to an authoritative schema field. `requested_fields` and `display_fields` must contain exactly the same fields in the same order. Do not silently substitute, add, or hide display fields. Keys, join fields, and filters that are needed only for execution belong in `support_fields` and are not displayed.
- If the user does not name return fields, use `mode: "inferred"`. Choose the smallest complete business view for the requested grain. Include the business identifier, the requested measure/status/date, and the contextual fields needed to interpret it. Do not use a fixed column cap and do not return only an identifier when the question needs evidence or context.
- For an aggregate, every `display_field` must be a `group_by`, legacy `sum_field`, or metric `output_field`; source-only fields are lost by the transform and cannot be displayed.
- `display_fields` are the only fields shown in the SAPClaw table. `support_fields` are fetched for safe execution, joins, filtering, or audit but remain hidden from presentation.

## Candidate Disambiguation

- When catalog or KG evidence identifies overlapping executable services, inspect schema and guidance for every material candidate before selecting one. Do not choose only the first broad catalog match.
- An API Skill's exact natural-language pattern, explicit business-object scope, or `When Not To Use` instruction outweighs a broader catalog description. Use that guidance to decide *which* schema to inspect and plan against; schema remains the authority for *whether* a field or path can execute.
- Do not assume two APIs that expose similarly named records have the same business grain. Prefer the candidate whose Skill most specifically matches the user's requested object, then compare its stable identifiers and measures against schema before execution.
- When a selected API Skill supplies an exact field list for a matching user pattern, treat that list as the required query grain. Do not add display-only names, ledger fields, optional dimensions, or convenience metadata unless the user explicitly requests them; analytical OData services can change aggregation grain and counts when `$select` changes.

## Pagination

- Show the first returned page only; do not load all pages into context automatically.
- Preserve `case_id` from the execution response.
- For "next page", call `sapclaw_runtime_page` with `next_skip`.
- For page N, calculate `skip = (N - 1) * page_size` and call `sapclaw_runtime_page`.
- Explain page-out-of-range and expired-case errors directly; do not rerun the original query unless the user asks.
- Do not offer a clickable local result-viewer link in Codex Desktop. The conversational page tools are the supported pagination surface in this client.
- A successful multi-row, pageable, or detailed query opens the system-browser viewer by default through `sapclaw_runtime_open_viewer`. Compact single-result answers remain in Codex; do not ask the user to click a local URL.

## Safety

- Read only. Do not propose POST, PATCH, PUT, MERGE, DELETE, payloads, custom headers, absolute SAP URLs, or external hosts.
- Do not read, print, summarize, or expose SAP credentials, API keys, authorization headers, environment files, or internal `_all_results` data.
- Reject CDS-only/API-view candidates unless schema reports an executable OData runtime.
- Use `fetch_all_for_binding` only when a later step needs all source keys. Respect the configured 5000-row binding limit and report an explicit limit error.
- Keep business limits separate from transport page size. A 50-row page is not a request to limit the business result to 50.

## Result Semantics

- Base conclusions only on returned selected fields.
- Do not convert configuration flags into completion status without schema/Skill evidence.
- For aggregates, request a validated `result_transform`; do not mentally aggregate an incomplete page. Use `deduplicate_by` for stable business keys, `count_distinct` for composite document-item counts, and a `currency_field` for monetary `sum` or `sum_abs` metrics.
- If evidence is insufficient, say what field, relation, or service is missing rather than guessing.

Read [references/plan-schema.md](references/plan-schema.md) when constructing multi-step, function-import, binding, or aggregate plans. Read [references/examples.md](references/examples.md) for compact tool-call examples.
