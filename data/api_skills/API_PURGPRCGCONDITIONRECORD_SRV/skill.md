# API_PURGPRCGCONDITIONRECORD_SRV Skill

## Purpose

Use this API for Consumers of this inbound service can create, read, update, and delete condition records inside your system by using OData requests. The service contains entities for condition record, validity of condition record, pricing scale, and condition supplement.. Consumers of this inbound service can create, read, update, and delete condition records inside your system by using OData requests. The service contains entities for condition record, validity of condition record, pricing scale, and condition supplement.

Keep `data/index/API_PURGPRCGCONDITIONRECORD_SRV` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about consumers of this inbound service can create, read, update, and delete condition records inside your system by using odata requests. the service contains entities for condition record, validity of condition record, pricing scale, and condition supplement. or the business objects exposed by this service: Purchasing Prcg Condition Record, Purchasing Prcg Cndn Record Scale, Purchasing Prcg Cndn Recd Suplmnt, Purchasing Prcg Cndn Recd Validity.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PURGPRCGCONDITIONRECORD_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_PurgPrcgConditionRecord`: Reads all condition records in the system.. Methods: DELETE, GET, PATCH, POST.
- `A_PurgPrcgCndnRecordScale`: Reads all pricing scales in the system.. Methods: DELETE, GET, PATCH, POST.
- `A_PurgPrcgCndnRecdSuplmnt`: Reads all condition supplements in the system.. Methods: DELETE, GET, PATCH, POST.
- `A_PurgPrcgCndnRecdValidity`: Reads validity of all condition records in the system.. Methods: GET, PATCH, POST.

## Business Semantics

- Primary business scope: Consumers of this inbound service can create, read, update, and delete condition records inside your system by using OData requests. The service contains entities for condition record, validity of condition record, pricing scale, and condition supplement..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PURGPRCGCONDITIONRECORD_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- If the user asks for purchasing pricing condition record records or the main identifying details of condition records, query `A_PurgPrcgConditionRecord` directly.
- Use `A_PurgPrcgCndnRecdValidity` only when the user asks for validity periods, validity dates, release status, supplier/material/org validity context, or other validity-level details.
- Use `A_PurgPrcgCndnRecordScale` only for pricing scale lines, scale quantities, or scale amounts.
- Use `A_PurgPrcgCndnRecdSuplmnt` only for condition supplements.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_PURGPRCGCONDITIONRECORD_SRV` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PURGPRCGCONDITIONRECORD_SRV` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
